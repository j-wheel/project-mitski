import asyncio
import itertools
import random
import re
import time
from collections import deque
from dataclasses import dataclass, field, replace

import discord

from mitski.brain.answers import answers_it
from mitski.brain.planner import Thought
from mitski.chat import convo, guard, shape
from mitski.chat.addressing import QUESTIONY
from mitski.chat.messages import clean
from mitski.chat.patterns import LIST_LINE, LOW_EFFORT, NEVER, PING_TAG, ROBOTIC, SERVILE
from mitski.chat.policy import explicit
from mitski.core import logs, voice
from mitski.core.collections import BoundedDict
from mitski.core.component import Component
from mitski.core.metrics import Metrics
from mitski.core.text import cut
from mitski.core.texts import fill, say, wording
from mitski.llm.client import ModelUnavailable, drop_unfinished, stopped_at_limit

log = logs.get("pipeline")

PLAN_SUMMARY = re.compile(
    r"What to tell them:|What happened, roughly:|What .{1,40} wants:|What you're going for:|If it fits, you could ask"
)
TYPING_SETTLE = 7
LIVE_SEC = 120
COLD_SHARE = 0.3
QUICK_PACE = (0.15, 0.45)
QUICK_DEBOUNCE = 0.5
BAIT_KINDS = {"injection", "ai talk", "work", "transcript"}
BAIT_WINDOW_SEC = 1800
BORED_AFTER = 3
IGNORE_BAIT_AFTER = 5
IGNORE_BAIT_CHANCE = 0.6
LET_GO_CHANCE = 0.8
MANY_LINES_REPLY_CHANCE = 0.7
SPACED_CHANCE = 0.5
LOOK_POLL_SEC = 30
SEEN_LATE_SEC = 180
CATCHING_UP_SEC = (5, 180)
PING_TOO_OLD_SEC = 3 * 3600
WANTS_ONE_BACK = re.compile(r"^(?:gn|gm)\b", re.I)
LONG_NOTE = wording("chat.long_answer")
LONG_ASK = re.compile(
    r"\b(explain|tell me (?:about|everything|more)|how (?:was|did|do|does)|what happened|walk me through|"
    r"any (?:advice|tips)|what should i do|help me (?:with|understand|figure))\b",
    re.I,
)
LONG_MESSAGE = 250


BRUSH_OFF_NOTE = wording("chat.brush_off_work")
GIST_NOTE = wording("chat.gist_of_work")
FAVOR_NOTE = wording("chat.doing_a_favor")


MISSED_NOTE = wording("chat.missed_message")


def time_words(seconds):
    minutes = max(1, round(seconds / 60))
    if minutes < 90:
        return say("chat.ago_minutes", minutes=minutes)
    hours = round(minutes / 60)
    return say("chat.ago_hours", hours=hours) if hours < 36 else say("chat.ago_days", days=round(hours / 24))


def too_few_answers(lines, questions):
    return lines < questions and (lines == 1 or questions - lines >= 2)


FIXES = wording("chat.fixes")


@dataclass
class Reply:
    channel: object
    mode: str
    key: tuple | None = None
    trigger: object = None
    job: int = 0
    owned: dict = field(default_factory=dict)
    waited: float = 0.0
    was_doing: str = ""
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
    minors: bool = False
    long: bool = False
    missed: float = 0.0
    recall: object = None
    ready_for: int | None = None
    inner: str = ""
    aim: int | None = None
    clean_retry: bool = False
    seen_as: object = None
    baited: int = 0

    @property
    def tag(self):
        return f"{self.mode} #{self.job}"

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
        self.missed = BoundedDict(200)
        self.jobs = itertools.count(1)
        self.baits = BoundedDict(500)

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

    def join_in(self, channel, msg, inner="", aim=None):
        self.app.tasks.spawn(
            self.respond(channel, "ambient", trigger=msg, inner=inner, aim=aim), name=f"ambient-{channel.id}"
        )

    async def _until_she_sees_it(self, mode, key):
        routine = self.app.routine
        msg = self.state.waiting.get(key) if key else None
        gid = getattr(getattr(msg, "guild", None), "id", None)
        if msg is None or routine.looking(gid):
            return 0.0, ""
        what = routine.doing(gid)
        kind = "dm" if mode == "dm" else "ping" if self.app.addressing.talks_to_her(msg) else "chat"
        start = routine.stamp()
        deadline = routine.notice_at(kind, guild_id=gid)
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

    async def respond(self, channel, mode, key=None, trigger=None, inner="", aim=None):
        if mode == "ambient" and not self.app.routine.free_in(getattr(getattr(channel, "guild", None), "id", None)):
            return
        waited, was_doing = await self._until_she_sees_it(mode, key)
        lock = self.state.channel_locks.setdefault(channel.id, asyncio.Lock())
        if mode == "ambient" and lock.locked():
            return
        async with lock:
            reply = Reply(
                channel,
                mode,
                key,
                trigger,
                job=next(self.jobs),
                waited=waited,
                was_doing=was_doing,
                inner=inner,
                aim=aim,
            )
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

    async def _admit(self, reply):
        if reply.key is not None:
            reply.trigger = self.state.waiting.get(reply.key)
        trigger = reply.trigger
        if trigger is None:
            return reply.stop("superseded")
        if reply.guild is not None and not self.messages.allowed_channel(reply.channel):
            return reply.stop("not her channel")
        age = (discord.utils.utcnow() - trigger.created_at).total_seconds()
        reply.missed = self.missed.pop(trigger.id, 0.0)
        if not reply.missed and self._too_old(reply, age):
            return reply.stop("stale")
        reply.here = self.messages.guild_id(reply.channel)
        reply.was_quiet = reply.here is not None and self.app.away.is_quiet(reply.here)
        if reply.here is not None and self.app.away.state(reply.here):
            return reply.stop("away")
        return True

    def _too_old(self, reply, age):
        if not reply.waited:
            return age > self.cfg.STALE_SEC
        if reply.mode == "dm":
            return False
        if self.app.addressing.talks_to_her(reply.trigger):
            return age > PING_TOO_OLD_SEC
        return age > self.cfg.STALE_SEC

    async def wait_quiet(self, key, max_wait=20.0, debounce=None):
        debounce = self.cfg.DEBOUNCE_SEC if debounce is None else debounce
        start = time.monotonic()
        while time.monotonic() - start < max_wait:
            now = time.monotonic()
            typing_at = self.state.last_typing.get(key, NEVER)
            sent_at = self.state.last_msg_time.get(key, NEVER)
            typed = typing_at <= sent_at or now - typing_at >= TYPING_SETTLE
            if now - sent_at >= debounce and typed:
                return
            await asyncio.sleep(0.25)

    def _pace(self, reply):
        chance = float(self.cfg.QUICK_REPLY_CHANCE)
        if reply.waited or chance <= 0 or reply.trigger is None:
            return 1.0
        cid, now = reply.channel.id, time.monotonic()
        last = self.app.sender.last_at.get(cid, NEVER)
        live = self.app.addressing.is_engaged(cid, reply.trigger.author.id) or now - last < LIVE_SEC
        if random.random() < (chance if live else chance * COLD_SHARE):
            return random.uniform(*QUICK_PACE)
        return 1.0

    async def _settle(self, reply):
        key = reply.key
        pace = self._pace(reply)
        debounce = self.cfg.DEBOUNCE_SEC * (QUICK_DEBOUNCE if pace < 1 else 1)
        if key is not None:
            await self.wait_quiet(key, debounce=debounce)
            reply.trigger = self.state.waiting.get(key, reply.trigger)
        delay = random.uniform(*self.cfg.READ_DELAY) + min(len(reply.trigger.content) / self.cfg.READ_CPS, 6)
        delay *= pace
        if pace < 1:
            log.debug("[%s] a quick one (x%.2f)", reply.tag, pace)
        elif reply.mode != "direct" and random.random() < self.cfg.DISTRACTED_CHANCE:
            delay += random.uniform(*self.cfg.DISTRACTED_DELAY)
        ready = self.app.tasks.spawn(self._get_ready(reply), name=f"ready-{reply.job}")
        await asyncio.sleep(delay)
        if key is not None:
            await self.wait_quiet(key, max_wait=10, debounce=debounce)
            reply.trigger = self.state.waiting.pop(key, reply.trigger)
            reply.took_key = True
        if ready.done() or getattr(reply.trigger, "id", None) != reply.ready_for:
            log.debug("[%s] got ready early: %s", reply.tag, "done" if ready.done() else "for an older message")
        return True

    async def _get_ready(self, reply):
        trigger = reply.trigger
        reply.ready_for = getattr(trigger, "id", None)
        try:
            early = Reply(reply.channel, reply.mode, reply.key, trigger, job=reply.job)
            if not await self._read(early, quiet=True):
                return
            if reply.trigger is trigger and early.target is not None:
                await self._think(early)
        except Exception:
            log.debug("[%s] getting ready early didn't work, it's done the normal way", reply.tag, exc_info=True)

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
                log.info("[%s] %s, not answering %s", reply.tag, self.app.away.state(reply.here), reply.target.author)
                return reply.stop("away")
            await self._write(reply)
            if attempt == 0 and reply.key is not None and reply.key in self.state.waiting:
                reply.trigger = self.state.waiting.pop(reply.key)
                log.info("[%s] %s said more, re-reading", reply.tag, reply.trigger.author)
                continue
            break
        return True

    async def _read(self, reply, quiet=False):
        reply.ctx = await self.app.context.build(reply.channel, reply.mode, reply.trigger, aim=reply.aim)
        if not reply.ctx.turns:
            return reply.stop("nothing to answer")
        addressing = self.app.addressing
        reply.burst = addressing.burst_of(reply.target, reply.ctx.msgs)
        reply.pieces = addressing.pieces_of(reply.burst)
        reply.said = addressing.burst_text(reply.burst)
        reply.to_her = reply.mode == "dm" or any(addressing.talks_to_her(m) for m in reply.burst)
        if self.cfg.MEMORY and not quiet:
            context = "\n".join(self.messages.text(m) for m in list(reply.ctx.msgs)[-6:])
            reply.recall = self.app.tasks.spawn(
                self.memory.prefetch(reply.target.author, context), name=f"recall-{reply.job}"
            )
        if len(reply.burst) > 1 and not quiet:
            log.info(
                "[%s] answering %d messages from %s together: %r",
                reply.tag,
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
        if not reply.direct or not self._small_talk(reply):
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
            "[%s] not replying to %s: it doesn't need a reply (%r)", reply.tag, target.author, clean(target.content)
        )
        if reply.mode == "direct":
            self.app.addressing.engage(reply.channel.id, target.author.id)
        if self.cfg.REACTIONS and random.random() < 0.5:
            await self.app.reactions.react(target, quick=True)

    async def _react_instead(self, reply):
        if not (
            self.cfg.REACTIONS
            and reply.direct
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
        log.info("[%s] reacted %s to %s: %r", reply.tag, emoji, target.author, target.content)
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
        return await self.app.brain.think(
            reply.mode,
            target,
            msgs,
            True,
            reply.channel,
            to_her=to,
            said=reply.said,
            parts=[p.text for p in reply.pieces] if len(reply.pieces) > 1 else None,
        )

    async def _plan(self, reply):
        target, channel = reply.target, reply.channel
        reply.thought = await self._think(reply)
        if reply.direct and self.app.feelings.leaves_on_read(target.author, reply.thought.reply_type):
            log.info("[%s] she doesn't like %s much, leaving it on read", reply.tag, target.author)
            Metrics.event("left on read")
            return reply.stop("left on read")
        if (
            reply.thought.reply_type == "no_reply"
            and self._owed(reply)
            and not reply.to_her
            and random.random() < LET_GO_CHANCE
        ):
            await self._leave_it(reply)
            return reply.stop("no reply needed")
        reply.extras = (
            [await self.app.youtube.notes(reply.ctx.msgs)]
            + reply.thought.notes
            + await self.app.scheduler.apply(reply.thought, target, channel)
        )
        if reply.inner:
            reply.extras.append(say("chat.inner_thought", thought=reply.inner))
        self._see_through(reply)
        if self._done_with_it(reply):
            log.info("[%s] %s keeps baiting her, she's not answering this one", reply.tag, target.author)
            Metrics.event("bored of the bait")
            if self.cfg.REACTIONS and random.random() < 0.5:
                await self.app.reactions.react(target, quick=True)
            return reply.stop("bored of the bait")
        if reply.missed:
            reply.extras.append(fill(MISSED_NOTE, ago=time_words(reply.missed + reply.waited)))
        elif reply.waited >= SEEN_LATE_SEC:
            reply.extras.append(self.app.routine.seen_late(reply.waited, reply.was_doing))
        chiming = self._chiming(reply)
        if chiming:
            name = self.messages.call(target.author)
            reply.extras.append(say("chat.chiming_in", name=name))
            log.info("[%s] chiming in on %s's message to someone else", reply.tag, target.author)
        self._human_ask(reply)
        self._split_topics(reply, chiming)
        reply.long = self._long(reply, chiming)
        if reply.long:
            reply.extras.append(LONG_NOTE)
        reply.extras_for = target.id
        return True

    def _human_ask(self, reply):
        thought = reply.thought
        if thought.ask == "effort":
            gist = cut(thought.brief, 120).rstrip(".") if thought.brief else ""
            reply.extras = [e for e in reply.extras if not PLAN_SUMMARY.match(str(e or ""))]
            reply.thought = thought.without_plan()
            if random.random() < self._brush_off_chance(reply):
                reply.extras.append(BRUSH_OFF_NOTE)
                Metrics.event("brushed off")
                log.info("[%s] that's a big ask, she brushes it off", reply.tag)
            else:
                reply.extras.append(fill(GIST_NOTE, gist=f" (like: {gist})" if gist else ""))
                log.info("[%s] that's a big ask, she just gives the gist", reply.tag)
        elif thought.ask == "favor" or thought.actions:
            reply.extras.append(FAVOR_NOTE)

    def _brush_off_chance(self, reply):
        chance = float(self.cfg.BRUSH_OFF_CHANCE)
        user = reply.target.author
        if self.app.feelings.like_of(user) >= 35:
            chance *= 0.6
        if not self.app.routine.can_hang_out_in(getattr(reply.guild, "id", None)):
            chance *= 1.4
        if self.app.feelings.mood_on and self.app.feelings.mood.level("tired") >= 0.35:
            chance *= 1.3
        return min(chance, 0.95)

    def _long(self, reply, chiming):
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
            log.info("[%s] it could use a longer reply, but she wrote one here not long ago", reply.tag)
            return False
        self.long_at[reply.channel.id] = now
        log.info("[%s] giving this one a longer reply", reply.tag)
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
        reply.extras.append(say("chat.several_questions", name=name, asked=asked))
        log.info("[%s] %s asked %d different things", reply.tag, reply.target.author, len(reply.things))

    async def _write(self, reply):
        ctx, target, mode = reply.ctx, reply.target, reply.mode
        if reply.recall is not None:
            await reply.recall
        elif self.cfg.MEMORY:
            await self.memory.prefetch(target.author, "\n".join(self.messages.text(m) for m in list(ctx.msgs)[-6:]))
        situation = self.app.situation
        await self.app.ages.settled(target.author)
        authors = list({m.author.id: m.author for m in ctx.everything if m.author.id != self.me.id}.values())
        reply.minors = situation.minors_among(authors)
        reply.adult = self.app.policy.adult_ok(reply.channel, minors=reply.minors)
        reply.persona = situation.persona(
            target.author, reply.guild, full=mode != "ambient", channel=reply.channel, people=authors, about=False
        )
        about = situation.about(target.author, full=mode != "ambient", channel=reply.channel)
        reply.notes = situation.notes(
            mode, reply.channel, target, ctx.msgs, reply.extras, ctx.around, reply.burst, about=about
        )
        if self.cfg.SHOW_NOTES:
            log.info("for %s:\n%s", target.author, reply.notes)
        out = await self.llm.generate(
            self.llm.prompt(ctx.turns, reply.persona, reply.notes), raw=True, cache_key=reply.channel.id
        )
        reply.text = out.get("content", "") if isinstance(out, dict) else str(out or "")
        if stopped_at_limit(out, self.cfg.MAX_TOKENS):
            log.info("[%s] her reply ran into MAX_TOKENS, leaving off the unfinished end", reply.tag)
            Metrics.event("reply out of room")
            reply.text = drop_unfinished(reply.text)

    async def _polish(self, reply):
        ctx, drafts, channel_id = reply.ctx, self.app.drafts, reply.channel.id
        reply.lines = drafts.tidy(reply.text, channel_id, ctx.others)
        seen = self._seen(reply)
        problem = (
            drafts.problem(
                reply.lines,
                seen,
                False,
                reply.adult,
                self._asked_directly(reply),
                channel=reply.channel,
                minors=reply.minors,
                said=reply.said,
                work=self._big_ask(reply),
                joking=self._joking(reply),
                baited=bool(reply.baited),
            )
            if reply.lines
            else None
        )
        if problem:
            log.info("[%s] reply looked %r, trying again: %s", reply.tag, problem, " | ".join(reply.lines))
            Metrics.event(f"redo {problem}")
            first = list(reply.lines)
            reply.lines = await self._retry(reply, self._fix_for(problem, reply), seen)
            if reply.clean_retry:
                self.app.preferences.keep(reply, first, reply.lines, problem)
            if not reply.lines:
                log.info("[%s] still no good reply, staying quiet", reply.tag)
                if reply.mode != "ambient" and self.cfg.REACTIONS:
                    await self.app.reactions.react(reply.trigger)
                return reply.stop("bad draft")
        if reply.lines and reply.things and too_few_answers(len(reply.lines), len(reply.things)):
            log.info("[%s] %d lines for %d questions, trying again", reply.tag, len(reply.lines), len(reply.things))
            Metrics.event("answer all retry")
            reply.lines = await self.app.review.answer_all(
                ctx.turns, reply.persona, reply.notes, reply.things, reply.channel, ctx.others, seen, reply.lines
            )
        thought = reply.thought
        if reply.lines and thought.wants_answer and not answers_it(reply.lines, thought.brief, thought.checked):
            log.info("[%s] reply didn't answer, trying again: %s", reply.tag, " | ".join(reply.lines))
            Metrics.event("answer retry")
            first = list(reply.lines)
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
                reply.tag,
            )
            if reply.lines != first:
                self.app.preferences.keep(reply, first, reply.lines, "didn't answer", self.app.review.answered_by)
        if reply.lines and await self.app.policy.judged_unsafe(reply.lines, reply.channel):
            log.info("[%s] the safety check turned it down, trying again: %s", reply.tag, " | ".join(reply.lines))
            Metrics.event("redo not safe")
            first = list(reply.lines)
            reply.lines = await self._retry(reply, FIXES["not safe"], seen)
            if not reply.lines or await self.app.policy.judged_unsafe(reply.lines, reply.channel):
                log.info("[%s] still not safe, staying quiet", reply.tag)
                if reply.mode != "ambient" and self.cfg.REACTIONS:
                    await self.app.reactions.react(reply.trigger)
                return reply.stop("not safe")
            if reply.clean_retry:
                self.app.preferences.keep(reply, first, reply.lines, "not safe")
        return bool(reply.lines) or reply.stop("empty draft")

    def _joking(self, reply):
        return reply.thought.reply_type == "joke" or reply.thought.mood in ("playful", "excited")

    def _big_ask(self, reply):
        return reply.thought.ask == "effort" or bool(reply.seen_as and reply.seen_as.work)

    def _see_through(self, reply):
        target = reply.target
        hers = list(self.state.recent_said.get(reply.channel.id, ())) + [
            self.messages.text(m) for m in reply.ctx.msgs if m.author.id == self.me.id
        ]
        texts = [self.messages.text(m) for m in reply.burst]
        seen = guard.read(texts, self.messages.call(target.author), hers, self.messages.own_names())
        reply.seen_as = seen
        reply.baited = self._bait_count(target.author.id, seen)
        if not seen.kinds:
            return
        log.info("[%s] %s's message looks like: %s", reply.tag, target.author, ", ".join(seen.kinds))
        Metrics.event("seen through: " + ", ".join(seen.kinds))
        if seen.injection:
            planned = set(reply.thought.notes)
            reply.extras = [e for e in reply.extras if e not in planned and not PLAN_SUMMARY.match(str(e or ""))]
            reply.thought = reply.thought.without_plan()
        if seen.work and reply.thought.ask != "effort":
            reply.thought = replace(reply.thought, ask="effort")
        reply.extras += seen.notes
        if reply.baited >= BORED_AFTER:
            reply.extras.append(fill(guard.BORED_NOTE, name=self.messages.call(target.author)))

    def _bait_count(self, uid, seen):
        if not seen.kinds or not set(seen.kinds) & BAIT_KINDS:
            times = self.baits.get(uid)
            return len([t for t in times if time.monotonic() - t < BAIT_WINDOW_SEC]) if times else 0
        times = self.baits.get(uid) or deque(maxlen=20)
        times.append(time.monotonic())
        self.baits[uid] = times
        return len([t for t in times if time.monotonic() - t < BAIT_WINDOW_SEC])

    def _done_with_it(self, reply):
        return reply.baited >= IGNORE_BAIT_AFTER and random.random() < IGNORE_BAIT_CHANCE

    def _fix_for(self, problem, reply):
        if problem == "ai game":
            return guard.FIX_AI_FRAME
        if problem == "doing the work":
            return guard.FIX_WORK
        if problem == "gibberish":
            return guard.FIX_GIBBERISH
        if problem == "repetitive":
            return guard.FIX_REPEAT
        if problem == "laughing at nothing":
            return guard.FIX_LAUGH
        if problem == "out of character":
            return self.app.identity.fix()
        if problem == "off topic":
            name = self.messages.call(reply.target.author)
            return say("chat.fix_random_hi", name=name, said=cut(reply.said, 200))
        return FIXES.get(problem, FIXES["robotic"])

    def _asked_directly(self, reply):
        return voice.asked_about_her(reply.said, reply.ctx.others)

    async def _retry(self, reply, fix, seen):
        drafts = self.app.drafts
        direct = self._asked_directly(reply)
        text = await self.llm.generate(
            self.llm.prompt(reply.ctx.turns, reply.persona, reply.notes + "\n" + fix),
            temperature=min(1.3, self.cfg.TEMPERATURE + 0.2),
            cache_key=reply.channel.id,
        )
        lines = drafts.tidy(text, reply.channel.id, reply.ctx.others)
        reply.clean_retry = False
        if lines and drafts.problem(
            lines,
            seen,
            False,
            reply.adult,
            direct,
            channel=reply.channel,
            minors=reply.minors,
            said=reply.said,
            work=self._big_ask(reply),
            joking=self._joking(reply),
            baited=bool(reply.baited),
        ):
            copied = set(drafts.echoed(lines, seen))
            kept = [
                ln
                for ln in lines
                if ln not in copied
                and not ROBOTIC.search(ln)
                and not SERVILE.search(ln)
                and not LIST_LINE.match(ln)
                and (reply.adult or not explicit(ln))
                and not self.app.policy.breaks(ln, reply.channel, reply.minors)
                and not self.app.identity.wrong(ln)
                and not guard.gibberish(ln)
                and ln not in drafts.repeated([ln], reply.channel)
                and not (reply.baited and guard.plays_the_ai_game([ln]))
                and not (direct and voice.opens_with_she(ln))
            ]
            lines = kept if sum(map(len, kept)) >= 0.5 * sum(map(len, lines)) else []
            if lines and drafts.problem(lines, seen, said=reply.said) == "off topic":
                lines = []
            if lines and guard.does_the_work(lines, asked=self._big_ask(reply)):
                lines = []
            if lines and guard.laughing_at_nothing(lines, reply.said, self._joking(reply)):
                lines = []
        elif lines:
            reply.clean_retry = True
        return lines

    async def _aim(self, reply):
        addressing = self.app.addressing
        if reply.mode == "ambient":
            reply.trigger = reply.target
        reply.anchor = addressing.anchor_of(reply.burst)
        if reply.things:
            reply.anchor = reply.things[-1].msg
        reply.addr = reply.anchor
        reply.owned = {m.id: m.author.id for m in [*reply.burst, reply.target]}
        log.debug("[%s] answering %s", reply.tag, ", ".join(str(i) for i in reply.owned))
        if reply.mode == "dm":
            await self._review(reply)
            return True
        reply.people = self.messages.people_in(reply.ctx.everything)
        verdict, other, mixed = await self._review(reply)
        if mixed:
            log.info("it gets who said what wrong, not sending it: %s", " | ".join(reply.lines))
            if self._owed(reply) and self.cfg.REACTIONS:
                await self.app.reactions.react(reply.anchor)
            return reply.stop("mixed up")
        if verdict == "other" and not await self._redirect(reply, other):
            return reply.stop("wrong message")
        if verdict == "general":
            reply.addr = reply.anchor if self._owed(reply) else None
        if self._too_late(reply):
            return reply.stop("too late")
        return True

    def _owed(self, reply):
        return reply.mode == "direct" and not self._chiming(reply)

    async def _review(self, reply):
        review, ctx, anchor = self.app.review, reply.ctx, reply.anchor
        owed = self._owed(reply) or reply.mode == "dm"
        verdict, other, mixed = await review.check(reply.lines, anchor, ctx.msgs, ctx.around, always=owed)
        if not (owed and (mixed or verdict in ("other", "general"))):
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
        v2, o2, m2 = await review.check(retry, anchor, ctx.msgs, ctx.around, always=owed)
        if not m2 and (v2 in (None, "fits") or mixed):
            log.info("rewritten for %s: %s", name, " | ".join(retry))
            reply.lines, reply.things = retry, None
            return v2, o2, m2
        log.info("the rewrite didn't work either: %s", " | ".join(retry))
        return verdict, other, mixed

    async def _redirect(self, reply, other):
        anchor, owed = reply.anchor, self._owed(reply)
        other_name = self.messages.call(other.author)
        if not owed and not self.app.review.already_answered(other):
            log.info("[%s] it fits %s's message better, so it goes out replying to nobody", reply.tag, other_name)
            reply.addr = None
            return True
        log.info(
            "[%s] it answers %s's message, not %s's: not sending it",
            reply.tag,
            other_name,
            self.messages.call(anchor.author),
        )
        Metrics.event("wrong target held back")
        if owed and self.requeue(reply.channel, anchor):
            log.info("[%s] %s's message gets a fresh try", reply.tag, self.messages.call(anchor.author))
        elif owed and self.cfg.REACTIONS:
            await self.app.reactions.react(anchor)
        return False

    def _after(self, reply):
        to_id = reply.addr.author.id if reply.addr is not None else None
        return to_id, self.app.review.authors_after(reply.channel, (reply.addr or reply.target).id, to_id)

    def _too_late(self, reply):
        if not (reply.mode == "ambient" or self._chiming(reply)):
            return False
        _, after = self._after(reply)
        if convo.too_late(after, self.me.id, self.cfg.LATE_GAP):
            log.info(
                "[%s] too much came in while she was typing, letting it go: %s", reply.tag, " | ".join(reply.lines)
            )
            return True
        return False

    def _plan_delivery(self, reply):
        here = reply.here
        if here is not None and (self.app.away.asleep(here) or self.app.away.is_quiet(here)):
            log.info("[%s] went %s while typing, not sending", reply.tag, self.app.away.state(here))
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
        crowded = any(a not in (self.me.id, to_id) for a in after)
        reply.layout = shape.pick(
            answers,
            serious=reply.serious,
            crowded=crowded,
            can_thread=bool(groups) and len(groups) >= 2 and crowded,
            longer=reply.long,
        )
        if reply.layout == shape.THREADED and not groups:
            reply.layout = shape.BLOCK
        if reply.layout == shape.THREADED:
            reply.parts, reply.targets = shape.threaded(groups, random)
        else:
            spaced = shape.paragraphs(answers, reply.long or reply.serious) and random.random() < SPACED_CHANCE
            reply.parts = answers if spaced else [reply.lines]
        if reply.layout != shape.QUICK:
            log.info("[%s] sending it as %s", reply.tag, reply.layout)

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
            owned=reply.owned,
            job=reply.job,
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
        self.app.blocking.said(shown, to_user)
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
        log.info("[%s] %s -> %s%s: %s%s", reply.tag, where, to_user or "the chat", how, " | ".join(shown), tag)
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
