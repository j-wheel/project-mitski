import asyncio
import random
import re
import time
from datetime import timedelta

import discord

from mitski.chat.messages import NORMAL_TYPES, clean, short_name
from mitski.chat.patterns import NEVER
from mitski.core import logs
from mitski.core.component import Component
from mitski.core.text import cut
from mitski.core.texts import say
from mitski.llm.client import ModelUnavailable

log = logs.get("dms")


DM_PROMISE = re.compile(
    r"\b(i'?ll|ill|ima|imma|i'?m gonna|im gonna|gonna|going to|let me|lemme|i will|about to|abt to|finna)\b"
    r"[^.!?\n]{0,25}?\b(dm|pm|message|msg|text|slide into)\b"
    r"|\bcheck (your|ur|yo|ya) (dms?|pms?|inbox)\b|\b(dming|messaging|texting) (you|u|ya)\b"
    r"|\b(move|moving|take|taking) (this|it) to (the )?dms\b",
    re.I,
)
PROMISE_NOT_FOR_THEM = re.compile(r"\s+(my|his|her|him|them|their|mom|dad|someone)\b", re.I)
USER_ASKS_DM = re.compile(
    r"\b(dm|pm|message|msg|text) me\b|\bslide (in|into) my dms\b|\b(can|could|should) (i|we|u|you) dm\b"
    r"|\bhop in dms\b|\b(go|move|take this|take it) to dms\b",
    re.I,
)
AGREE = re.compile(r"\b(ok(ay)?|kk?|sure|bet|fine|yes|yea|yeah|ya+|yup|alr|alright|omw|on it|say less|deal)\b", re.I)
REFUSE = re.compile(r"\b(no+|nah|nope|never|ew+|later|maybe|not)\b", re.I)
CATCH_UP_START = (30, 90)
CATCH_UP_GAP = (40, 120)
FRIEND_GAP = (20, 60)


def find_promise(text):
    for line in text.split("\n"):
        for m in DM_PROMISE.finditer(line):
            if PROMISE_NOT_FOR_THEM.match(line[m.end() :]):
                continue
            return line, m
    return None


class DirectMessages(Component):
    def __init__(self, app):
        super().__init__(app)
        self.friend_requests = set()
        self.friend_skipped = set()
        self.accepting = asyncio.Lock()

    def accept_pending(self):
        for relationship in list(getattr(self.app.client, "relationships", None) or []):
            self.friend_request(relationship)

    def friend_request(self, relationship):
        user = relationship.user
        if not self.cfg.FRIEND_ACCEPT or relationship.type is not discord.RelationshipType.incoming_request:
            return
        if user.id in self.friend_requests or user.id in self.friend_skipped:
            return
        if user.bot or user.id in self.cfg.ignored or self.app.ages.is_minor(user):
            log.info("%s sent her a friend request, leaving it", user)
            return
        self.friend_requests.add(user.id)
        self.app.tasks.spawn(self._accept(user), name="friend-request")

    async def _accept(self, user):
        try:
            await asyncio.sleep(random.uniform(*self.cfg.FRIEND_ACCEPT_DELAY))
            async with self.accepting:
                relationship = self.app.client.get_relationship(user.id)
                if relationship is None or relationship.type is not discord.RelationshipType.incoming_request:
                    log.info("%s's friend request is gone", user)
                    return
                try:
                    await relationship.accept()
                except discord.CaptchaRequired:
                    self.friend_skipped.add(user.id)
                    log.warning("discord wants a captcha for %s's friend request, skipping it until she restarts", user)
                    return
                except discord.HTTPException as e:
                    log.warning("couldn't accept %s's friend request: %s", user, e)
                    return
                log.info("accepted %s's friend request", user)
                await asyncio.sleep(random.uniform(*FRIEND_GAP))
        finally:
            self.friend_requests.discard(user.id)

    async def catch_up(self):
        if not self.cfg.DM_CATCH_UP:
            return
        await asyncio.sleep(random.uniform(*CATCH_UP_START))
        missed = []
        for channel in list(getattr(self.app.client, "private_channels", None) or []):
            if not isinstance(channel, discord.DMChannel):
                continue
            try:
                found = await self._missed(channel)
            except discord.HTTPException as e:
                log.info("couldn't read the dm with %s: %s", getattr(channel, "recipient", "?"), e)
                continue
            if found:
                missed.append(found)
        missed.sort(key=lambda m: m.id, reverse=True)
        if missed:
            log.info("%d dms came in while she was offline, catching up", len(missed))
        for i, msg in enumerate(missed[: self.cfg.DM_CATCH_UP_MAX]):
            if i:
                await asyncio.sleep(random.uniform(*CATCH_UP_GAP))
            if self._answered_since(msg):
                continue
            age = (discord.utils.utcnow() - msg.created_at).total_seconds()
            log.info("catching up on %s's dm from %.0f min ago: %r", msg.author, age / 60, cut(msg.content, 60))
            self.app.router.catch_up(msg, age)

    async def _missed(self, channel):
        newest = getattr(channel, "last_message_id", None)
        window = self.cfg.DM_CATCH_UP_HOURS * 3600
        if newest and (discord.utils.utcnow() - discord.utils.snowflake_time(newest)).total_seconds() > window:
            return None
        msgs = [m async for m in channel.history(limit=10) if m.type in NORMAL_TYPES]
        if not msgs:
            return None
        last = msgs[0]
        author = last.author
        if author.id == self.me.id or author.bot or author.id in self.cfg.ignored or not self.messages.usable(last):
            return None
        if (discord.utils.utcnow() - last.created_at).total_seconds() > window:
            return None
        try:
            request = bool(channel.is_message_request())
        except AttributeError:
            request = False
        if request and not any(m.author.id == self.me.id for m in msgs):
            log.info("%s sent her a message request, leaving it", author)
            return None
        return last

    def _answered_since(self, msg):
        if (msg.channel.id, msg.author.id) in self.state.waiting:
            return True
        last = self.app.sender.last_sent.get(msg.channel.id)
        return last is not None and last > msg.id

    def is_friend(self, user):
        friends = getattr(self.app.client, "friends", None) or ()
        return any(getattr(getattr(r, "user", None), "id", None) == user.id for r in friends)

    def may_start_dm(self, user):
        if user.bot or self.app.ages.is_minor(user):
            return False
        return self.cfg.DM_ENABLED or (self.cfg.DM_ENABLED_FRIEND and self.is_friend(user))

    def note_exchange(self, user, channel):
        if not self.may_start_dm(user) or not self.app.routine.free or not self.app.feelings.close_enough_to_dm(user):
            return
        now = time.monotonic()
        times = self.state.exchanges[user.id]
        times.append(now)
        while times and now - times[0] > self.cfg.dm_window:
            times.popleft()
        if len(times) < self.cfg.DM_MIN_EXCHANGES:
            return
        if user.id in self.state.dm_unanswered:
            return
        if now - self.state.dm_opened.get(user.id, NEVER) < self.cfg.dm_cooldown:
            return
        if now - self.state.dm_rolled.get(user.id, NEVER) < self.cfg.dm_window:
            return
        self.state.dm_rolled[user.id] = now
        roll = random.random()
        log.info(
            "%s qualifies (%d exchanges), rolled %.2f vs %s -> %s",
            user,
            len(times),
            roll,
            self.cfg.DM_CHANCE,
            "dm" if roll < self.cfg.DM_CHANCE else "no",
        )
        if roll < self.cfg.DM_CHANCE:
            self.app.tasks.spawn(self.open(user, channel), name=f"dm-open-{user.id}")

    def check_promise(self, lines, their_msg, msgs, channel):
        if not self.cfg.DM_KEEP_PROMISES or their_msg is None or isinstance(channel, discord.DMChannel):
            return
        said = "\n".join(lines)
        promise = find_promise(said)
        asked = USER_ASKS_DM.search(clean(their_msg.content)) and AGREE.search(said) and not REFUSE.search(said)
        if not promise and not asked:
            return
        user = their_msg.author
        if promise:
            line, m = promise
            after = line[m.end() : m.end() + 24].lower()
            people = {}
            for msg in msgs:
                if msg.author.id != self.me.id and not msg.author.bot:
                    people[short_name(msg.author).lower()] = msg.author
                    people[msg.author.name.lower()] = msg.author
            for n, u in people.items():
                if len(n) >= 3 and re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", after):
                    user = u
                    break
        if user.bot:
            return
        now = time.monotonic()
        if (
            now - self.state.dm_promised.get(user.id, NEVER) < self.cfg.dm_promise_cooldown
            or now - self.state.dm_opened.get(user.id, NEVER) < 600
        ):
            return
        self.state.dm_promised[user.id] = now
        self.state.dm_rolled[user.id] = now
        log.info("she said she'd dm %s, keeping her word", user)
        self.app.tasks.spawn(self.open(user, channel, promise=said), name=f"dm-promise-{user.id}")

    async def open(self, user, channel, promise=None):
        await asyncio.sleep(random.uniform(*(self.cfg.DM_PROMISE_DELAY if promise else self.cfg.DM_DELAY)))
        try:
            if not promise and not (self.may_start_dm(user) and self.app.routine.free):
                return
            dm = user.dm_channel or await user.create_dm()
            if not promise:
                last = [m async for m in dm.history(limit=1)]
                if last and discord.utils.utcnow() - last[0].created_at < timedelta(seconds=self.cfg.dm_cooldown):
                    return

            msgs = list(reversed(await self.app.context.thread_with(channel, None, user.id)))
            turns = self.app.context.to_turns(msgs, need_user_last=False) or []
            theirs = [m for m in msgs if m.author.id == user.id]
            anchor = theirs[-1] if theirs else None
            if promise:
                note = say("dms.promised", name=self.messages.call(user), channel=channel, promise=cut(promise, 200))
                if not turns or turns[-1][0] == "assistant":
                    turns.append(["user", ""])
                notes = self.app.situation.notes("dm_open", dm, anchor, msgs, [note]) if anchor else note
                prompt = self.llm.prompt(turns, self.app.situation.persona(user), notes)
            else:
                if not turns:
                    return
                note = say("dms.sliding_in", name=self.messages.call(user), channel=channel)
                notes = self.app.situation.notes("dm_open", dm, anchor, msgs, [note]) if anchor else note
                prompt = self.llm.prompt(turns, self.app.situation.persona(user), notes, reopen=True)
            text = await self.llm.generate(prompt)
            lines = self.app.drafts.tidy(
                text, dm.id, sorted({short_name(user), self.messages.call(user)} | self.messages.speaker_names())
            )
            if not lines:
                return

            self.state.dm_opened[user.id] = time.monotonic()
            self.state.dm_unanswered.add(user.id)
            sent = await self.app.sender.send(dm, lines)
            if not sent:
                return
            self.app.sender.remember(sent, user.id)
            self.memory.her_said(user, lines)
            mode = "dm_promise" if promise else "dm_open"
            log.info("[%s] -> %s: %s", mode, user, " | ".join(lines))
            theirs = [m for m in msgs if m.author.id == user.id]
            await self.app.relay.interaction(
                mode,
                dm,
                user,
                theirs[-1] if theirs else None,
                lines,
                turns=len(turns),
                label=f"last thing they said in #{channel}",
            )
        except discord.Forbidden:
            self.state.dm_opened[user.id] = time.monotonic()
            log.warning("%s has dms closed", user)
        except ModelUnavailable as e:
            log.warning("llm request failed, no dm: %s", e)
        except Exception:
            log.warning("dm error", exc_info=True)
