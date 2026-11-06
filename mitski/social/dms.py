import asyncio
import random
import re
import time
from datetime import timedelta

import discord

from mitski.chat.messages import clean, short_name
from mitski.chat.patterns import NEVER
from mitski.core import logs
from mitski.core.component import Component
from mitski.core.text import cut
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


def find_promise(text):
    for line in text.split("\n"):
        for m in DM_PROMISE.finditer(line):
            if PROMISE_NOT_FOR_THEM.match(line[m.end() :]):
                continue
            return line, m
    return None


class DirectMessages(Component):
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
                note = (
                    f'You just told {self.messages.call(user)} in #{channel} that you\'d dm them (you said: "{cut(promise, 200)}"). '
                    f"This is that dm, you're messaging them like you said you would. "
                    f"Pick up from what you were talking about, don't make a big deal of it."
                )
                if not turns or turns[-1][0] == "assistant":
                    turns.append(["user", ""])
                notes = self.app.situation.notes("dm_open", dm, anchor, msgs, [note]) if anchor else note
                prompt = self.llm.prompt(turns, self.app.situation.persona(user), notes)
            else:
                if not turns:
                    return
                note = (
                    f"You're sliding into {self.messages.call(user)}'s DMs after chatting with them in #{channel}. "
                    f"Keep going from what you were talking about, like a friend would."
                )
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
