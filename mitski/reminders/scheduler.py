import asyncio
import re
import time
from datetime import datetime

import discord

from mitski.chat.messages import short_name
from mitski.core import logs
from mitski.core.clock import ago
from mitski.core.component import Component
from mitski.reminders.timing import describe, due_time

log = logs.get("reminders")


class ReminderScheduler(Component):
    @property
    def store(self):
        return self.app.reminders

    async def apply(self, thought, target, channel):
        request = (getattr(thought, "actions", None) or {}).get("remind")
        if not request or not self.store.on:
            return []
        what = re.sub(r"\s+", " ", str(request.get("what") or "")).strip().rstrip(".")
        if not what:
            return []
        now = self.app.clock.now()
        existing = self.store.by_source(target.id)
        if existing is not None:
            when = datetime.fromtimestamp(existing.due, now.tzinfo)
            return [f"You already set that reminder: {describe(when, now)}. Just confirm it, short."]
        guild = getattr(channel, "guild", None)
        who = self.messages.resolve_person(request.get("who"), guild, asker=target.author, context=[target])
        if who is None:
            return [
                f"They want you to remind {request.get('who')} about something, but you don't know who that is, so ask."
            ]
        if who.id in self.cfg.ignored:
            return []
        when = due_time(request.get("said") or self.messages.text(target), request, now)
        problem = self._problem(when, now, target.author)
        if problem:
            return [problem]
        r = self.store.add(
            who.id, target.author.id, channel.id, getattr(guild, "id", None), when.timestamp(), what, target.id
        )
        them = "them" if who.id == target.author.id else self.messages.call(who)
        log.info("#%d for %s %s: %s", r.id, who, describe(when, now), what)
        await self.app.relay.post(
            f"**reminder #{r.id} set** by {target.author.display_name} for {getattr(who, 'display_name', who.name)}, "
            f"{describe(when, now)}: {what}"
        )
        return [
            f"You'll remind {them} {describe(when, now)}: {what}. You'll ping {them} then. Tell "
            f"{self.messages.call(target.author)} ok, short and casual (you can say when)."
        ]

    def _problem(self, when, now, asker):
        if when is None:
            return "They want a reminder but didn't say when (or you couldn't tell), so ask them when."
        secs = (when - now).total_seconds()
        if secs < 50:
            return "That reminder would be right now, so just tell them now instead."
        if secs > self.store.max_days * 86400:
            return f"That's too far ahead for you to remember (more than {self.store.max_days:g} days), say so."
        if not self.app.owner.is_owner(asker) and self.store.pending_from(asker.id) >= self.store.max_per_user:
            return "They already asked you for a bunch of reminders, so say you can't keep track of more right now."
        return None

    async def _destination(self, r, user):
        channel = self.app.get_channel(r.channel)
        if (
            channel is not None
            and getattr(channel, "guild", None) is not None
            and not self.messages.allowed_channel(channel)
        ):
            channel = None
        if channel is None:
            channel = user.dm_channel or await user.create_dm()
        return channel

    async def _write(self, r, user, channel):
        by = self.app.get_user(r.by)
        when_asked = ago(r.made, time.time())
        note = (
            f"It's time to remind {self.messages.call(user)} about: {r.what}. "
            + (
                f"They asked you {when_asked}. "
                if r.for_themselves or by is None
                else f"{self.messages.call(by)} asked you to remind them ({when_asked}). "
            )
            + ("You're a bit late with it. " if time.time() - r.due > 600 else "")
            + "Write the reminder to them now, short and in your own words, like texting a friend."
        )
        persona = self.app.situation.persona(user, getattr(channel, "guild", None))
        names = sorted({short_name(user), self.messages.call(user)} | self.messages.speaker_names())
        try:
            text = await self.llm.generate(self.llm.prompt([["user", ""]], persona, note))
            lines = self.app.drafts.tidy(text, channel.id, names)
        except Exception:
            log.warning("writing reminder #%d failed, sending a plain one", r.id, exc_info=True)
            lines = []
        return lines or [f"hey reminder: {r.what}"]

    async def deliver(self, r):
        try:
            user = self.app.get_user(r.user) or await self.app.fetch_user(r.user)
            channel = await self._destination(r, user)
        except discord.HTTPException:
            log.warning("can't reach the person for reminder #%d, dropping it", r.id)
            self.store.done(r.id)
            return
        lines = await self._write(r, user, channel)
        original = None
        if r.msg and r.for_themselves and channel.id == r.channel:
            try:
                original = await channel.fetch_message(r.msg)
            except discord.HTTPException:
                original = None
        try:
            sent = await self.app.sender.send(channel, lines[:3], reply_to=original, ping=user, reply_ping=False)
            self.app.sender.remember(sent, user.id)
            log.info("#%d -> %s: %s", r.id, user, " | ".join(lines))
            await self.app.relay.post(f"**reminded** {user.display_name} (#{r.id}): {r.what}")
        except discord.HTTPException:
            log.warning("couldn't send reminder #%d", r.id, exc_info=True)
        self.store.done(r.id)

    async def tick(self):
        for r in self.store.due_now():
            if r.guild and self.app.away.is_quiet(r.guild):
                continue
            await self.deliver(r)

    async def run(self):
        await asyncio.sleep(15)
        while True:
            try:
                await self.tick()
            except Exception:
                log.warning("reminder check failed", exc_info=True)
            await asyncio.sleep(15)
