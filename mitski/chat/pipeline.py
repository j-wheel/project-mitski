import asyncio
import random
import re
import time
from contextlib import nullcontext
from dataclasses import dataclass, field

import discord

from mitski.brain.answers import answers_it
from mitski.brain.planner import Thought
from mitski.chat import convo, shape
from mitski.chat.addressing import QUESTIONY
from mitski.chat.messages import clean
from mitski.chat.patterns import LOW_EFFORT, NEVER, PING_TAG, ROBOTIC
from mitski.chat.policy import explicit
from mitski.core import logs, voice
from mitski.core.component import Component
from mitski.core.metrics import Metrics
from mitski.core.text import cut
from mitski.llm.client import ModelUnavailable

log = logs.get("pipeline")

PLAN_SUMMARY = re.compile(r"What to tell them:|What happened, roughly:|What .{1,40} wants:")
TYPING_SETTLE = 7
LET_GO_CHANCE = 0.8
BLANK_LINES_CHANCE = 0.5
MANY_LINES_REPLY_CHANCE = 0.7
LOOK_POLL_SEC = 30
SEEN_LATE_SEC = 180
CATCHING_UP_SEC = (5, 180)
PING_TOO_OLD_SEC = 3 * 3600
WANTS_ONE_BACK = re.compile(r"^(?:gn|gm)\b", re.I)
LONG_NOTE = (
    "This one deserves a proper answer, so you can write more than you usually do: a few full sentences, or a few "
    "messages in a row, still in your own style and voice. Say what's worth saying, don't pad it out."
)
LONG_ASK = re.compile(
    r"\b(explain|tell me (?:about|everything|more)|how (?:was|did|do|does)|what happened|walk me through|"
    r"any (?:advice|tips)|what should i do|help me (?:with|understand|figure))\b",
    re.I,
)
LONG_MESSAGE = 250


def too_few_answers(lines, questions):
    """One line for several questions, or two or more questions with no line at all. Texting merges answers, so
    two lines for three questions is fine."""
    return lines < questions and (lines == 1 or questions - lines >= 2)


FIXES = {
    "echo": "Don't repeat or copy anything anyone said, reply to it in your own words.",
    "robotic": "Talk like yourself, a person, not like an assistant.",
    "explicit": "Keep it PG-13 here: nothing sexual, you can't know how old people are.",
    "third person": "You're talking about yourself, so say i, me and my. Never your own name or she/her.",
}


@dataclass
class Reply:
    channel: object
    mode: str
    key: tuple | None = None
    trigger: object = None
    waited: float = 0.0
    was_doing: str = ""
    boss: bool = False
    here: int | None = None
    was_quiet: bool = False
    took_key: bool = False
    typing_since: float = 0.0
    ctx: object = None
    burst: list = field(default_factory=list)
    pieces: list = field(default_factory=list)
    said: str = ""
    to_her: bool = False
    thought: Thought = field(default_factory=Thought)
    extras: list = field(default_factory=list)
    extras_for: int | None = None
    things: list | None = None
    parts: list | None = None
    layout: str = shape.QUICK
    targets: list | None = None
    persona: str = ""
    notes: str = ""
    text: str = ""
    lines: list = field(default_factory=list)
    anchor: object = None
    addr: object = None
    people: dict | None = None
    delivery: object = None
    sent: list = field(default_factory=list)
    outcome: str = "dropped"
    adult: bool = False
    long: bool = False

    @property
    def guild(self):
        return getattr(self.channel, "guild", None)

    @property
    def target(self):
        return self.ctx.target if self.ctx is not None else self.trigger

    @property
    def direct(self):
        return self.mode in ("direct", "dm")

    @property
    def serious(self):
        return self.thought.reply_type in ("comfort", "help")

    def stop(self, why):
        self.outcome = why
        return False


class ReplyPipeline(Component):
    def __init__(self, app):
        super().__init__(app)
        self.long_at = {}

    def queue(self, channel, mode, msg):
        key = (channel.id, msg.author.id)
        self.state.last_msg_time[key] = time.monotonic()
        self.app.vision.warm(msg)
        fresh = key not in self.state.waiting
        self.state.waiting[key] = msg
        if fresh:
            self.app.tasks.spawn(self.respond(channel, mode, key=key), name=f"reply-{channel.id}-{msg.author.id}")

    def requeue(self, channel, msg):
        if msg.id in self.state.requeued:
            return False
        self.state.requeued.add(msg.id)
        key = (channel.id, msg.author.id)
        if key not in self.state.waiting:
            self.state.waiting[key] = msg
            self.app.tasks.spawn(self.respond(channel, "direct", key=key), name=f"requeue-{msg.id}")
        return True

    def join_in(self, channel, msg):
        self.app.tasks.spawn(self.respond(channel, "ambient", trigger=msg), name=f"ambient-{channel.id}")

    async def _until_she_sees_it(self, mode, key):
        routine = self.app.routine
        msg = self.state.waiting.get(key) if key else None
        gid = getattr(getattr(msg, "guild", None), "id", None)
        if msg is None or routine.looking(gid):
            return 0.0, ""
        what = routine.doing(gid)
        kind = "dm" if mode == "dm" else "ping" if self.app.addressing.talks_to_her(msg) else "chat"
        start = routine.stamp()
        deadline = routine.notice_at(kind, owner=self.app.owner.is_owner(msg.author), guild_id=gid)
        log.info("[%s] she's %s, she'll see %s's message in %.0f min", mode, what, msg.author, (deadline - start) / 60)
        while key in self.state.waiting and not routine.looking(gid):
            left = deadline - routine.stamp()
            if left <= 0:
                routine.look()
                break
            await asyncio.sleep(min(left, LOOK_POLL_SEC))
        waited = routine.stamp() - start
        if waited >= SEEN_LATE_SEC:
            await asyncio.sleep(random.uniform(*CATCHING_UP_SEC))
        return waited, what

    async def respond(self, channel, mode, key=None, trigger=None):
        if mode == "ambient" and not self.app.routine.free_in(getattr(getattr(channel, "guild", None), "id", None)):
            return
        waited, was_doing = await self._until_she_sees_it(mode, key)
        lock = self.state.channel_locks.setdefault(channel.id, asyncio.Lock())
        if mode == "ambient" and lock.locked():
            return
        async with lock:
            reply = Reply(channel, mode, key, trigger, waited=waited, was_doing=was_doing)
            with self.app.metrics.trace(mode) as trace:
                try:
                    await self._run(reply)
                except ModelUnavailable as e:
                    reply.stop("model unavailable")
                    if not self.llm.breaker.open:
                        log.warning("llm request failed: %s (is llama-server running at %s?)", e, self.cfg.llm_url)
                except discord.HTTPException as e:
                    reply.stop("discord error")
                    log.warning("discord error in %s: %s", channel.id, e)
                except Exception:
                    reply.stop("crashed")
                    log.exception("replying in %s failed", channel.id)
                finally:
                    self._finish(reply)
                if trace.first_send is None:
                    trace.outcome = reply.outcome
                log.debug("[%s] %s", mode, trace.summary())

    async def _run(self, reply):
        stages = (
            ("admit", self._admit),
            ("settle", self._settle),
            ("compose", self._compose),
            ("polish", self._polish),
            ("aim", self._aim),
            ("deliver", self._deliver),
            ("aftercare", self._aftercare),
        )
        for name, stage in stages:
            with Metrics.stage(name):
                if not await stage(reply):
                    return

    def _finish(self, reply):
        key, channel = reply.key, reply.channel
        still_waiting = key is not None and self.state.waiting.get(key) is reply.trigger
        if still_waiting and not reply.took_key and reply.trigger is not None:
            self.state.waiting.pop(key, None)
        if reply.mode != "dm":
            self.app.ambient.new_threshold(channel.id)
            self.state.last_active[channel.id] = time.monotonic()
        if reply.mode == "ambient":
            self.state.ambient_times[channel.id].append(time.monotonic())

    def _gone_quiet(self, reply):
        here = reply.here
        return here is not None and (self.app.away.asleep(here) or (reply.was_quiet and self.app.away.is_quiet(here)))

    def _seen(self, reply):
        return reply.ctx.everything + self.state.last_history.get(reply.channel.id, [])[:20]

    def _typing(self, reply):
        return self.app.voice.typing_in(reply.channel)

    async def _admit(self, reply):
        if reply.key is not None:
            reply.trigger = self.state.waiting.get(reply.key)
        trigger = reply.trigger
        if trigger is None:
            return reply.stop("superseded")
        if reply.guild is not None and not self.messages.allowed_channel(reply.channel):
            return reply.stop("not her channel")
        reply.boss = self.app.owner.is_owner(trigger.author)
        age = (discord.utils.utcnow() - trigger.created_at).total_seconds()
        if self._too_old(reply, age):
            return reply.stop("stale")
        reply.here = self.messages.guild_id(reply.channel)
        reply.was_quiet = reply.here is not None and self.app.away.is_quiet(reply.here)
        if reply.here is not None and self.app.away.state(reply.here) and not reply.boss:
            return reply.stop("away")
        return True

    def _too_old(self, reply, age):
        if reply.boss:
            return False
        if not reply.waited:
            return age > self.cfg.STALE_SEC
        if reply.mode == "dm":
            return False
        if self.app.addressing.talks_to_her(reply.trigger):
            return age > PING_TOO_OLD_SEC
        return age > self.cfg.STALE_SEC

    async def wait_quiet(self, key, max_wait=20.0):
        start = time.monotonic()
        while time.monotonic() - start < max_wait:
            now = time.monotonic()
            typed = now - self.state.last_typing.get(key, NEVER) >= TYPING_SETTLE
            if now - self.state.last_msg_time.get(key, NEVER) >= self.cfg.DEBOUNCE_SEC and typed:
                return
            await asyncio.sleep(0.5)

    async def _settle(self, reply):
        key = reply.key
        if key is not None:
            await self.wait_quiet(key)
            reply.trigger = self.state.waiting.get(key, reply.trigger)
        delay = random.uniform(*self.cfg.READ_DELAY) + min(len(reply.trigger.content) / self.cfg.READ_CPS, 6)
        if reply.mode != "direct" and not reply.boss and random.random() < self.cfg.DISTRACTED_CHANCE:
            delay += random.uniform(*self.cfg.DISTRACTED_DELAY)
        await asyncio.sleep(delay)
        if key is not None:
            await self.wait_quiet(key, max_wait=10)
            reply.trigger = self.state.waiting.pop(key, reply.trigger)
            reply.took_key = True
        return True

    async def _compose(self, reply):
        reply.typing_since = time.monotonic()
        for attempt in range(2):
            if not await self._read(reply):
                return False
            if attempt == 0 and await self._let_go_of_it(reply):
                return reply.stop("no reply needed")
            if attempt == 0 and await self._react_instead(reply):
                return reply.stop("reacted")
            if reply.extras_for != reply.target.id and not await self._plan(reply):
                return False
            if self._gone_quiet(reply):
                log.info("[%s] %s, not answering %s", reply.mode, self.app.away.state(reply.here), reply.target.author)
                return reply.stop("away")
            await self._write(reply)
            if attempt == 0 and reply.key is not None and reply.key in self.state.waiting:
                reply.trigger = self.state.waiting.pop(reply.key)
                log.info("[%s] %s said more, re-reading", reply.mode, reply.trigger.author)
                continue
            break
        return True

    async def _read(self, reply):
        reply.ctx = await self.app.context.build(reply.channel, reply.mode, reply.trigger)
        if not reply.ctx.turns:
            return reply.stop("nothing to answer")
        addressing = self.app.addressing
        reply.burst = addressing.burst_of(reply.target, reply.ctx.msgs)
        reply.pieces = addressing.pieces_of(reply.burst)
        reply.said = addressing.burst_text(reply.burst)
        reply.to_her = reply.mode == "dm" or any(addressing.talks_to_her(m) for m in reply.burst)
        if len(reply.burst) > 1:
            log.info(
                "[%s] answering %d messages from %s together: %r",
                reply.mode,
                len(reply.burst),
                reply.target.author,
                reply.said[:120],
            )
        return True

    def _small_talk(self, reply):
        return all(LOW_EFFORT.match(clean(m.content)) for m in reply.burst)

    def _chiming(self, reply):
        return reply.mode == "direct" and not reply.to_her and self.app.addressing.for_someone_else(reply.target)

    def _closes_the_chat(self, reply):
        burst = reply.burst
        if reply.boss or not reply.direct or not self._small_talk(reply):
            return False
        if any(self.app.addressing.called_her(m) or WANTS_ONE_BACK.match(clean(m.content)) for m in burst):
            return False
        hers = [m for m in reply.ctx.msgs if m.author.id == self.me.id and m.id < burst[0].id]
        return bool(hers) and not QUESTIONY.search(self.messages.text(hers[-1]))

    async def _let_go_of_it(self, reply):
        if not self._closes_the_chat(reply) or random.random() >= LET_GO_CHANCE:
            return False
        await self._leave_it(reply)
        return True

    async def _leave_it(self, reply):
        target = reply.target
        log.info(
            "[%s] not replying to %s: it doesn't need a reply (%r)", reply.mode, target.author, clean(target.content)
        )
        if reply.mode == "direct":
            self.app.addressing.engage(reply.channel.id, target.author.id)
        if self.cfg.REACTIONS and random.random() < 0.5:
            await self.app.reactions.react(target, quick=True)

    async def _react_instead(self, reply):
        if not (
            self.cfg.REACTIONS
            and reply.direct
            and not reply.boss
            and not any(self.app.addressing.called_her(m) for m in reply.burst)
            and self._small_talk(reply)
            and random.random() < self.cfg.REACT_INSTEAD_CHANCE
        ):
            return False
        target = reply.target
        emoji = await self.app.reactions.react(target)
        if emoji is None:
            return False
        if reply.mode == "direct":
            self.app.addressing.engage(reply.channel.id, target.author.id)
        log.info("[%s] reacted %s to %s: %r", reply.mode, emoji, target.author, target.content)
        await self.app.relay.post(
            f"**reacted instead of replying** {emoji}\n**{target.author.display_name}:** "
            f"{cut(target.clean_content, 300)}\n[Jump to message]({target.jump_url})"
        )
        return True

    async def _think(self, reply):
        target, msgs = reply.target, reply.ctx.msgs
        if not self.app.brain.enabled:
            return Thought([await self.app.search.quick_lookup(target, msgs)])
        if reply.to_her:
            to = "her"
        elif reply.mode == "direct":
            to = "someone_else" if self.app.addressing.for_someone_else(target) else "her"
        else:
            to = None
        async with self._typing(reply) if not reply.was_quiet else nullcontext():
            return await self.app.brain.think(
                reply.mode,
                target,
                msgs,
                True,
                reply.channel,
                to_her=to,
                owner=self.app.owner.is_owner(target.author) and reply.mode != "ambient",
                orders=self.app.owner.orders_listing(),
                said=reply.said,
                parts=[p.text for p in reply.pieces] if len(reply.pieces) > 1 else None,
            )

    async def _plan(self, reply):
        target, channel = reply.target, reply.channel
        reply.thought = await self._think(reply)
        if reply.direct and self.app.feelings.leaves_on_read(target.author, reply.thought.reply_type):
            log.info("[%s] she doesn't like %s much, leaving it on read", reply.mode, target.author)
            Metrics.event("left on read")
            return reply.stop("left on read")
        if (
            reply.thought.reply_type == "no_reply"
            and self._owed(reply)
            and not reply.to_her
            and not self.app.owner.is_owner(target.author)
            and random.random() < LET_GO_CHANCE
        ):
            await self._leave_it(reply)
            return reply.stop("no reply needed")
        reply.extras = (
            [await self.app.youtube.notes(reply.ctx.msgs)]
            + reply.thought.notes
            + await self.app.requests.apply(reply.thought, target, channel)
            + await self.app.scheduler.apply(reply.thought, target, channel)
        )
        if reply.waited >= SEEN_LATE_SEC:
            reply.extras.append(self.app.routine.seen_late(reply.waited, reply.was_doing))
        chiming = self._chiming(reply)
        if chiming:
            name = self.messages.call(target.author)
            reply.extras.append(
                f"{name}'s message was to someone else, not you. You're just chiming in like a friend in the group "
                f"chat would, so react to it or add something, don't answer it as if it was for you, and don't "
                f"repeat it."
            )
            log.info("[%s] chiming in on %s's message to someone else", reply.mode, target.author)
        self._split_topics(reply, chiming)
        reply.long = self._long(reply, chiming)
        if reply.long:
            reply.extras.append(LONG_NOTE)
        reply.extras_for = target.id
        return True

    def _long(self, reply, chiming):
        """Whether this reply may be longer than usual. Her planner says when the moment calls for it, and this
        keeps it occasional: only when someone's talking to her, not while she's busy, and not again too soon."""
        if not (self.cfg.LONG_REPLIES and reply.direct) or chiming:
            return False
        if self.app.brain.enabled:
            wanted = reply.thought.length == "longer"
        else:
            wanted = bool(LONG_ASK.search(reply.said)) or len(reply.said) >= LONG_MESSAGE
        if not wanted or not self.app.routine.can_hang_out_in(getattr(reply.guild, "id", None)):
            return False
        now = time.monotonic()
        if now - self.long_at.get(reply.channel.id, NEVER) < self.cfg.LONG_REPLY_COOLDOWN_MIN * 60:
            log.info("[%s] it could use a longer reply, but she wrote one here not long ago", reply.mode)
            return False
        self.long_at[reply.channel.id] = now
        log.info("[%s] giving this one a longer reply", reply.mode)
        Metrics.event("longer reply")
        return True

    def _split_topics(self, reply, chiming):
        reply.things = None
        if not (self.cfg.MULTI_ANSWER and len(reply.pieces) > 1 and reply.direct and not chiming):
            return
        things = self.app.addressing.separate_things(reply.pieces, reply.thought)
        name = self.messages.call(reply.target.author)
        if len(things) < 2:
            return
        reply.extras = [e for e in reply.extras if not PLAN_SUMMARY.match(str(e or ""))]
        reply.thought = reply.thought.without_plan()
        reply.things = things[-self.cfg.MAX_LINES :]
        asked = " / ".join(f'"{cut(t.text, 120)}"' for t in reply.things)
        reply.extras.append(
            f"{name} asked you a few different questions: {asked}. Answer every one of them the way you'd text it: "
            f"a short line each, or one line that covers two if that's more natural, in whatever order fits. Use "
            f"your own words, never repeat theirs back."
        )
        log.info("[%s] %s asked %d different things", reply.mode, reply.target.author, len(reply.things))

    async def _write(self, reply):
        ctx, target, mode = reply.ctx, reply.target, reply.mode
        if self.cfg.MEMORY:
            await self.memory.prefetch(target.author, "\n".join(self.messages.text(m) for m in list(ctx.msgs)[-6:]))
        situation = self.app.situation
        await self.app.ages.settled(target.author)
        authors = list({m.author.id: m.author for m in ctx.everything if m.author.id != self.me.id}.values())
        reply.adult = self.app.policy.adult_ok(reply.channel, minors=situation.minors_among(authors))
        reply.persona = situation.persona(
            target.author, reply.guild, full=mode != "ambient", channel=reply.channel, people=authors
        )
        reply.notes = situation.notes(mode, reply.channel, target, ctx.msgs, reply.extras, ctx.around, reply.burst)
        if self.cfg.SHOW_NOTES:
            log.info("for %s:\n%s", target.author, reply.notes)
        async with self._typing(reply):
            reply.text = await self.llm.generate(self.llm.prompt(ctx.turns, reply.persona, reply.notes))

    async def _polish(self, reply):
        ctx, drafts, channel_id = reply.ctx, self.app.drafts, reply.channel.id
        reply.lines = drafts.tidy(reply.text, channel_id, ctx.others)
        seen = self._seen(reply)
        problem = (
            drafts.problem(reply.lines, seen, False, reply.adult, self._asked_directly(reply)) if reply.lines else None
        )
        if problem:
            log.info("[%s] reply looked %r, trying again: %s", reply.mode, problem, " | ".join(reply.lines))
            Metrics.event(f"redo {problem}")
            reply.lines = await self._retry(reply, FIXES.get(problem, FIXES["robotic"]), seen)
            if not reply.lines:
                log.info("[%s] still no good reply, staying quiet", reply.mode)
                if reply.mode != "ambient" and self.cfg.REACTIONS:
                    await self.app.reactions.react(reply.trigger)
                return reply.stop("bad draft")
        if reply.lines and reply.things and too_few_answers(len(reply.lines), len(reply.things)):
            log.info("[%s] %d lines for %d questions, trying again", reply.mode, len(reply.lines), len(reply.things))
            Metrics.event("answer all retry")
            async with self._typing(reply):
                reply.lines = await self.app.review.answer_all(
                    ctx.turns, reply.persona, reply.notes, reply.things, reply.channel, ctx.others, seen, reply.lines
                )
        thought = reply.thought
        if reply.lines and thought.wants_answer and not answers_it(reply.lines, thought.brief, thought.checked):
            log.info("[%s] reply didn't answer, trying again: %s", reply.mode, " | ".join(reply.lines))
            Metrics.event("answer retry")
            async with self._typing(reply):
                reply.lines = await self.app.review.make_her_answer(
                    ctx.turns,
                    reply.persona,
                    reply.notes,
                    thought,
                    reply.target,
                    ctx.msgs,
                    reply.channel,
                    ctx.others,
                    seen,
                    reply.lines,
                    reply.mode,
                )
        return bool(reply.lines) or reply.stop("empty draft")

    def _asked_directly(self, reply):
        return voice.asked_about_her(reply.said, reply.ctx.others)

    async def _retry(self, reply, fix, seen):
        drafts = self.app.drafts
        direct = self._asked_directly(reply)
        async with self._typing(reply):
            text = await self.llm.generate(
                self.llm.prompt(reply.ctx.turns, reply.persona, reply.notes + "\n" + fix),
                temperature=min(1.3, self.cfg.TEMPERATURE + 0.2),
            )
        lines = drafts.tidy(text, reply.channel.id, reply.ctx.others)
        if lines and drafts.problem(lines, seen, False, reply.adult, direct):
            copied = set(drafts.echoed(lines, seen))
            kept = [
                ln
                for ln in lines
                if ln not in copied
                and not ROBOTIC.search(ln)
                and (reply.adult or not explicit(ln))
                and not (direct and voice.opens_with_she(ln))
            ]
            lines = kept if sum(map(len, kept)) >= 0.5 * sum(map(len, lines)) else []
        return lines

    async def _aim(self, reply):
        addressing = self.app.addressing
        if reply.mode == "ambient":
            reply.trigger = reply.target
        reply.anchor = addressing.anchor_of(reply.burst)
        if reply.things:
            reply.anchor = reply.things[-1].msg
        reply.addr = reply.anchor
        if reply.mode == "dm":
            return True
        reply.people = self.messages.people_in(reply.ctx.everything)
        async with self._typing(reply):
            verdict, other, mixed = await self._review(reply)
        if mixed:
            log.info("it gets who said what wrong, not sending it: %s", " | ".join(reply.lines))
            if self._owed(reply) and self.cfg.REACTIONS:
                await self.app.reactions.react(reply.anchor)
            return reply.stop("mixed up")
        if verdict == "other" and not await self._redirect(reply, other):
            return reply.stop("already answered")
        if verdict == "general":
            reply.addr = reply.anchor if self._owed(reply) else None
        if self._too_late(reply):
            return reply.stop("too late")
        return True

    def _owed(self, reply):
        return reply.mode == "direct" and not self._chiming(reply)

    async def _review(self, reply):
        review, ctx, anchor = self.app.review, reply.ctx, reply.anchor
        verdict, other, mixed = await review.check(reply.lines, anchor, ctx.msgs, ctx.around)
        if not (self._owed(reply) and (mixed or verdict in ("other", "general"))):
            return verdict, other, mixed
        name = self.messages.call(anchor.author)
        why = "mixes up who said what" if mixed else verdict
        if not mixed and other is not None:
            why += f": answers {self.messages.call(other.author)}"
        log.info("reply doesn't work for %s's message (%s), rewriting it: %s", name, why, " | ".join(reply.lines))
        Metrics.event("refocus")
        retry = await review.refocus(
            ctx.turns,
            reply.persona,
            reply.notes,
            anchor,
            reply.burst,
            reply.thought,
            reply.channel,
            ctx.others,
            self._seen(reply),
        )
        if not retry:
            return verdict, other, mixed
        v2, o2, m2 = await review.check(retry, anchor, ctx.msgs, ctx.around)
        if not m2 and (v2 in (None, "fits") or mixed):
            log.info("rewritten for %s: %s", name, " | ".join(retry))
            reply.lines, reply.things = retry, None
            return v2, o2, m2
        log.info("the rewrite didn't work either: %s", " | ".join(retry))
        return verdict, other, mixed

    async def _redirect(self, reply, other):
        anchor, owed = reply.anchor, self._owed(reply)
        other_name = self.messages.call(other.author)
        if self.app.review.already_answered(other):
            log.info("that answers %s's message, which she already answered: not sending it twice", other_name)
            if owed and self.requeue(reply.channel, anchor):
                log.info("%s still gets an answer, next", self.messages.call(anchor.author))
            elif owed and self.cfg.REACTIONS:
                await self.app.reactions.react(anchor)
            return False
        log.info("it answers %s's message, so it goes there", other_name)
        reply.addr = other
        if owed and other.author.id != anchor.author.id and self.requeue(reply.channel, anchor):
            log.info("%s still gets an answer, next", self.messages.call(anchor.author))
        return True

    def _after(self, reply):
        to_id = reply.addr.author.id if reply.addr is not None else None
        return to_id, self.app.review.authors_after(reply.channel, (reply.addr or reply.target).id, to_id)

    def _too_late(self, reply):
        if not (reply.mode == "ambient" or self._chiming(reply)):
            return False
        _, after = self._after(reply)
        if convo.too_late(after, self.me.id, self.cfg.LATE_GAP):
            log.info(
                "[%s] too much came in while she was typing, letting it go: %s", reply.mode, " | ".join(reply.lines)
            )
            return True
        return False

    def _plan_delivery(self, reply):
        here = reply.here
        if here is not None and (
            self.app.away.asleep(here) or (self.app.away.is_quiet(here) and (reply.was_quiet or not reply.boss))
        ):
            log.info("[%s] went %s while typing, not sending", reply.mode, self.app.away.state(here))
            return None
        if reply.mode == "dm":
            reply.delivery = convo.Delivery("plain", reply.anchor, reply.anchor.author)
            return reply.delivery
        if self._too_late(reply):
            return None
        to_id, after = self._after(reply)
        addr = reply.addr
        d = convo.decide(
            addr,
            after,
            self.me.id,
            explicit=reply.to_her,
            reply_back=self.cfg.REPLY_BACK_CHANCE,
            casual_reply=(
                max(self.cfg.ACTIVE_REPLY_CHANCE, MANY_LINES_REPLY_CHANCE)
                if len(reply.lines) >= 2
                else self.cfg.ACTIVE_REPLY_CHANCE
            ),
            ping_chance=self.cfg.PING_CHANCE,
            crowded=bool(to_id and self.app.addressing.juggling(reply.channel.id, to_id)),
            can_ping=addr is not None and self.app.sender.may_ping(addr.author),
        )
        since = [a for a in after if a not in (self.me.id, d.to_id)]
        d.reply_ping = self.cfg.reply_ping if self.cfg.reply_ping != "auto" else bool(since)
        if reply.layout == shape.THREADED:
            d.kind, d.msg, d.user = "reply", addr, addr.author
        reply.delivery = d
        return d

    async def _answer_groups(self, reply):
        things = reply.things
        if not things or reply.mode == "dm" or reply.addr is not reply.anchor or len({t.msg.id for t in things}) < 2:
            return None
        owners = await self.app.review.match_answers(reply.lines, things)
        return shape.group_answers(reply.lines, owners) if owners else None

    async def _lay_out(self, reply):
        groups = await self._answer_groups(reply)
        if groups:
            reply.lines = [ln for _, lines in groups for ln in lines]
            answers = [lines for _, lines in groups]
            if len(groups) == 1:
                reply.addr = groups[0][0]
        elif reply.things and len(reply.lines) == len(reply.things):
            answers = [[ln] for ln in reply.lines]
        else:
            answers = [reply.lines]
        to_id, after = self._after(reply)
        reply.layout = shape.pick(
            answers,
            serious=reply.serious,
            crowded=any(a not in (self.me.id, to_id) for a in after),
            can_thread=bool(groups) and len(groups) >= 2,
            longer=reply.long,
        )
        if reply.layout == shape.THREADED and not groups:
            reply.layout = shape.BLOCK
        if reply.layout == shape.THREADED:
            reply.parts, reply.targets = shape.threaded(groups, random)
        else:
            spaced = len(answers) >= 2 and random.random() < BLANK_LINES_CHANCE
            reply.parts = answers if spaced else [reply.lines]
        if reply.layout != shape.QUICK:
            log.info("[%s] sending it as %s", reply.mode, reply.layout)

    async def _deliver(self, reply):
        await self._lay_out(reply)
        reply.sent = await self.app.sender.send(
            reply.channel,
            reply.lines,
            already_typed=time.monotonic() - reply.typing_since,
            serious=reply.serious,
            people=reply.people,
            plan=lambda: self._plan_delivery(reply),
            parts=reply.parts,
            layout=reply.layout,
            targets=reply.targets,
            longer=reply.long,
        )
        if not reply.sent or reply.delivery is None:
            return reply.stop("not sent")
        reply.outcome = "sent"
        return True

    async def _aftercare(self, reply):
        channel, mode, trigger, delivery = reply.channel, reply.mode, reply.trigger, reply.delivery
        shown = [m.content for m in reply.sent if getattr(m, "content", None)] or reply.lines
        to_user = delivery.user or (trigger.author if reply.direct else None)
        talking_to = to_user.id if to_user is not None else None
        sender = self.app.sender
        sender.remember(reply.sent, talking_to)
        self.app.routine.keep_around()
        if to_user is not None:
            self.memory.her_said(to_user, reply.lines)
        extra, extra_msg = await self.app.extras.after_reply(channel, reply.lines)
        if extra_msg:
            sender.remember([extra_msg], talking_to)
        chance = self.cfg.REACT_CHANCE if mode != "ambient" else self.cfg.REACT_CHANCE / 2
        if self.cfg.REACTIONS and random.random() < chance:
            self.app.tasks.spawn(
                self.app.reactions.react(trigger, quick=True, delay=random.uniform(0.5, 3)), name="react-after"
            )
        self._engage(reply, shown, talking_to)
        where = "dm" if mode == "dm" else f"#{channel}"
        tag = (" [gif]" if extra.startswith("http") else f" [{extra}]") if extra else ""
        how = "" if mode == "dm" else f" ({delivery.describe(self.messages.call)})"
        log.info("[%s] %s -> %s%s: %s%s", mode, where, to_user or "the chat", how, " | ".join(shown), tag)
        their_msg = delivery.msg or trigger
        await self.app.relay.interaction(
            mode, channel, to_user or trigger.author, their_msg, shown, extra, len(reply.ctx.turns)
        )
        if mode != "dm":
            self.app.dms.check_promise(reply.lines, their_msg, reply.ctx.msgs, channel)
        if mode == "direct":
            self.app.dms.note_exchange(trigger.author, channel)
        if reply.direct:
            self.memory.maybe_update(trigger.author, channel)
        return True

    def _engage(self, reply, shown, talking_to):
        addressing, channel_id = self.app.addressing, reply.channel.id
        if reply.mode in ("direct", "ambient") and talking_to:
            refill = reply.mode == "ambient" or talking_to != reply.trigger.author.id
            addressing.engage(channel_id, talking_to, refill=refill)
        if reply.mode != "dm":
            for uid in {int(i) for s in shown for i in PING_TAG.findall(s)} - {talking_to}:
                addressing.engage(channel_id, uid, refill=True)
