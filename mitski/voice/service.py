import asyncio
import importlib
import random
import re
import time
from collections import deque

import discord

from mitski.core import logs
from mitski.core.clock import DAY, per_tick
from mitski.core.collections import BoundedDict
from mitski.core.component import Component
from mitski.core.texts import fill, say, wording
from mitski.voice.rooms import RoomPicker, joinable
from mitski.voice.session import Session
from mitski.voice.sounds import Typing, TypingSounds
from mitski.voice.talk import VoiceTalk

log = logs.get("voice")

VC_TALK = re.compile(
    r"\b(?:vc|voice ?chat|voice channel|voice call|discord call|in (?:the )?call|on call|(?:hop|jump|get|come) "
    r"(?:on|in|into|to) (?:the )?(?:vc|call|voice)|join (?:the |my |our )?(?:vc|call|voice)|who'?s in (?:vc|call))\b",
    re.I,
)
INVITE = re.compile(r"\b(?:join|come|hop|jump|get)\b.{0,25}\b(?:vc|call|voice)\b|\b(?:vc|call)\s*\?", re.I)
LEAVE = re.compile(
    r"\b(?:leave|get out of|dip from|disconnect from|dc from|go out of|get off)\b.{0,15}\b(?:vc|call|voice)\b"
    r"|\bhang(?:ing)? up\b",
    re.I,
)
CALL_ALONE_WAIT = (20, 60)
CALL_NOTE = wording("voice.in_call_quiet")
CALL_TALK_NOTE = wording("voice.in_call_talking")
QUIET_IN_VC = wording("voice.quiet_in_vc")
TALKS_IN_VC = wording("voice.talks_in_vc")
DECISION_NOTES = wording("voice.decisions")


class Voice(Component):
    def __init__(self, app):
        super().__init__(app)
        self.sounds = TypingSounds(
            app.cfg.paths.sounds / (self.cfg.VOICE_ASMR_FILE or "asmr.mp3"), self.cfg.VOICE_ASMR_VOLUME
        )
        self.rooms = RoomPicker(self.people, muted=lambda channel: self.messages.muted(channel))
        self.problem = None
        self.vc = None
        self.session = None
        self.busy = False
        self.cooldown_until = 0.0
        self.joins = deque()
        self.vc_talk = {}
        self.decisions = BoundedDict(300)
        self.answering = set()
        self.talk = VoiceTalk(app)

    @property
    def on(self):
        return self.cfg.VOICE_MODE != "off"

    @property
    def active(self):
        return self.on and self.problem is None

    @property
    def tick(self):
        return self.cfg.VOICE_CHECK_SEC

    def check(self):
        if not self.on:
            return
        missing = [name for module, name in (("nacl", "PyNaCl"), ("davey", "davey")) if not _importable(module)]
        if missing:
            self.problem = (
                f'{" and ".join(missing)} not installed, run: pip install -U "discord.py-self[voice]" '
                f"(needs discord.py-self 2.1.0+, discord only lets encrypted clients into voice now)"
            )
            return
        if not discord.opus.is_loaded():
            try:
                discord.opus._load_default()
            except Exception:
                log.debug("loading opus failed", exc_info=True)
        if not discord.opus.is_loaded():
            self.problem = "opus isn't loaded (linux: apt install libopus0)"
            return
        self.sounds.load()

    def status(self):
        if not self.on:
            return "off"
        if self.problem:
            return f"off ({self.problem})"
        talk = f", talking {self.talk.status()}" if self.talk.on else ""
        return f"on, {self.sounds.status()}{talk}"

    def typing_in(self, channel):
        return Typing(self.sounds, channel)

    def people(self, channel):
        out = []
        for uid in getattr(channel, "voice_states", {}):
            if (self.me and uid == self.me.id) or uid in self.cfg.ignored:
                continue
            member = channel.guild.get_member(uid)
            if member is not None and member.bot:
                continue
            out.append(uid)
        return out

    def where(self, guild):
        if self.vc is None or self.session is None or self.session.call:
            return None
        if getattr(guild, "id", None) != self.session.guild:
            return None
        return self.vc.channel

    def in_call(self, channel):
        s = self.session
        return self.vc is not None and s is not None and s.call and s.guild == getattr(channel, "id", None)

    def call_note(self, channel, call_name):
        if not self.in_call(channel):
            return ""
        call = getattr(self.vc.channel, "call", None)
        users = [self.app.get_user(u) for u in self._call_people(call)]
        names = [call_name(u) for u in users if u is not None]
        note = fill(CALL_TALK_NOTE if self.talk.live else CALL_NOTE, who=", ".join(names[:6]) or "them")
        heard = self.talk.note()
        return f"{note} {heard}" if heard else note

    def note(self, guild, call_name):
        channel = self.where(guild)
        if channel is None:
            return ""
        members = [channel.guild.get_member(u) for u in self.people(channel)]
        names = [call_name(m) for m in members if m is not None]
        company = f" with {', '.join(names[:6])}" if names else ", alone"
        where = say("voice.in_vc", channel=channel.name, company=company, minutes=int(self.session.minutes))
        if not self.talk.live:
            return say("voice.in_vc_quiet", where=where)
        heard = self.talk.note()
        talking = say("voice.in_vc_talking", where=where)
        return f"{talking} {heard}" if heard else talking

    def decision_note(self, msg_id):
        note = DECISION_NOTES.get(self.decisions.get(msg_id), "")
        return note.replace("{vc}", TALKS_IN_VC if self.talk.on else QUIET_IN_VC)

    def _away(self, guild_id):
        return self.app.away.state(guild_id) is not None

    def heard_in_dm(self, msg):
        if not self.active or not self.in_call(msg.channel) or not LEAVE.search(msg.content or ""):
            return None
        leave = random.random() < self.cfg.VOICE_ASKED_CHANCE
        if leave:
            self.app.tasks.spawn(self.leave("asked to hang up", delay=random.uniform(2, 8)), name="call-leave")
        return self._decide(msg, "leave" if leave else "stay")

    def heard(self, msg, to_her):
        if not self.active or msg.guild is None or self._away(msg.guild.id):
            return None
        text = msg.content or ""
        here = self.where(msg.guild)
        if here is not None and to_her and LEAVE.search(text):
            leave = random.random() < self.cfg.VOICE_ASKED_CHANCE
            if leave:
                self.app.tasks.spawn(self.leave("asked to", delay=random.uniform(3, 12)), name="voice-leave")
            return self._decide(msg, "leave" if leave else "stay")
        if not VC_TALK.search(text):
            return None
        self.vc_talk[msg.guild.id] = time.time()
        invited = bool(to_her and INVITE.search(text))
        if here is not None:
            return None
        target, why = self.rooms.pick(msg, self.me.id)
        if target is None:
            return None
        if invited:
            ok = self.can_join() and random.random() < self.cfg.VOICE_ASKED_CHANCE
        else:
            ok = self.can_join() and random.random() < self.cfg.VOICE_TALK_CHANCE
            if not ok:
                return None
        if ok:
            reason = "asked" if invited else "people talked about vc"
            self.app.tasks.spawn(
                self.join(
                    target,
                    f"{reason}, {why}" if why else reason,
                    delay=random.uniform(8, 40),
                    solo=not self.people(target),
                ),
                name="voice-join",
            )
        return self._decide(msg, "join" if ok else "no")

    def _decide(self, msg, what):
        self.decisions[msg.id] = what
        return what

    def can_join(self, force=False):
        if not self.active or self.busy or (self.vc is not None and not force):
            return False
        now = time.time()
        while self.joins and now - self.joins[0] > DAY:
            self.joins.popleft()
        if force:
            return True
        return now >= self.cooldown_until and len(self.joins) < self.cfg.VOICE_MAX_PER_DAY

    async def join(self, channel, why, delay=0.0, solo=False):
        if delay:
            await asyncio.sleep(delay)
        if not self.can_join() or not joinable(channel):
            return
        self.busy = True
        try:
            vc = await channel.connect(
                timeout=30, reconnect=True, self_mute=False, self_deaf=False, cls=self.talk.client_class()
            )
        except Exception:
            log.warning("couldn't join %s", channel.name, exc_info=True)
            self.cooldown_until = time.time() + 600
            return
        finally:
            self.busy = False
        ids = self.people(channel)
        stay = random.uniform(*self.cfg.VOICE_STAY_MIN) * 60 * (0.6 if self.app.clock.late else 1.0)
        self.vc = vc
        self.session = Session(
            guild=channel.guild.id,
            stay_until=time.time() + stay,
            why=why,
            solo=solo,
            peak=len(ids),
            had_company=bool(ids),
        )
        self.sounds.attach(vc, channel.guild.id)
        self.talk.attach(vc)
        self.joins.append(time.time())
        log.info(
            "joined %s / %s (%s), %d people, staying ~%.0f min",
            channel.guild.name,
            channel.name,
            why,
            len(ids),
            stay / 60,
        )
        await self.app.relay.post(
            f"**joined vc** {channel.guild.name} / {channel.name} ({why}), {len(ids)} people in it"
        )

    # ---- calls in dms and group dms: she picks up when someone calls her, and never calls anyone herself ----

    def _rung(self, call):
        me = self.me
        return me is not None and any(getattr(u, "id", None) == me.id for u in (getattr(call, "ringing", None) or []))

    def _call_people(self, call):
        if call is None:
            return []
        me = getattr(self.me, "id", None)
        return [u for u in (getattr(call, "voice_states", None) or {}) if u != me and u not in self.cfg.ignored]

    def call_changed(self, call):
        if not (self.active and self.cfg.VOICE_CALLS) or not self._rung(call):
            return
        cid = call.channel.id
        if cid in self.answering or self.in_call(call.channel):
            return
        caller = getattr(call, "initiator", None)
        if caller is not None and caller.id in self.cfg.ignored:
            log.info("%s is calling her, but she ignores them", caller)
            return
        low, high = (list(self.cfg.VOICE_CALL_PICKUP_SEC) + [3, 12])[:2]
        self.answering.add(cid)
        self.app.tasks.spawn(self.pick_up(call, random.uniform(min(low, high), max(low, high))), name=f"pickup-{cid}")

    async def pick_up(self, call, delay):
        cid = call.channel.id
        try:
            await asyncio.sleep(delay)
            live = getattr(call.channel, "call", None) or call
            if not self._rung(live):
                log.info("the call stopped ringing before she picked up")
                return
            if self.vc is not None:
                await self.leave("someone called her")
            if self.vc is not None or self.busy:
                return
            self.busy = True
            try:
                vc = await live.connect(timeout=30, reconnect=True, cls=self.talk.client_class())
            except Exception:
                log.warning("couldn't pick up the call", exc_info=True)
                return
            finally:
                self.busy = False
            ids = self._call_people(live)
            caller = getattr(live, "initiator", None)
            who = self._call_label(live.channel)
            self.vc = vc
            self.session = Session(
                guild=cid,
                stay_until=float("inf"),
                why=f"{caller or 'someone'} called her",
                solo=False,
                peak=len(ids),
                had_company=bool(ids),
                call=True,
            )
            self.sounds.attach(vc, cid, everywhere=True)
            self.talk.attach(vc)
            log.info("picked up a call: %s, %d people in it", who, len(ids))
            await self.app.relay.post(f"**picked up a call** {who}, {len(ids)} people in it")
        finally:
            self.answering.discard(cid)

    def call_ended(self, call):
        self.answering.discard(call.channel.id)
        if self.in_call(call.channel):
            self.app.tasks.spawn(self.leave("the call ended"), name="call-ended")

    def _call_label(self, channel):
        name = getattr(channel, "name", None)
        if name:
            return f"group dm {name}"
        recipient = getattr(channel, "recipient", None)
        return f"dm with {recipient}" if recipient is not None else "a dm call"

    async def _check_call(self, vc, s):
        ids = self._call_people(getattr(vc.channel, "call", None))
        now = time.time()
        s.peak = max(s.peak, len(ids))
        if ids:
            s.had_company, s.alone_since, s.alone_wait = True, None, None
            return
        if s.alone_since is None:
            s.alone_since, s.alone_wait = now, random.uniform(*CALL_ALONE_WAIT)
        if now - s.alone_since >= s.alone_wait:
            await self.leave("everyone else hung up")

    async def move(self, channel, why):
        if self.vc is None or self.busy or not joinable(channel):
            return
        self.busy = True
        try:
            await self.vc.move_to(channel)
            self.session.moved(self.people(channel))
            log.info("moved to %s (%s)", channel.name, why)
            await self.app.relay.post(f"**moved vc** to {channel.guild.name} / {channel.name} ({why})")
        except Exception:
            log.warning("couldn't move to %s", channel.name, exc_info=True)
        finally:
            self.busy = False

    async def leave(self, why, delay=0.0):
        if delay:
            await asyncio.sleep(delay)
        if self.vc is None or self.busy:
            return
        for _ in range(60):
            if not self.sounds.heard_typing() and not self.talk.replying.locked():
                break
            await asyncio.sleep(1)
        if self.vc is None:
            return
        vc, session = self.vc, self.session
        self.busy = True
        try:
            self.talk.detach()
            self.sounds.stop()
            name = self._call_label(vc.channel) if session.call else getattr(vc.channel, "name", "vc")
            await vc.disconnect(force=False)
            log.info("left %s after %.0f min (%s)", name, session.minutes, why)
            await self.app.relay.post(f"**left vc** {name} after {session.minutes:.0f} min ({why})")
        except Exception:
            log.warning("leaving failed", exc_info=True)
        finally:
            self._reset(self.cfg.VOICE_COOLDOWN_MIN * 60 * random.uniform(0.8, 1.5))
            self.busy = False

    def _reset(self, cooldown):
        self.talk.detach()
        self.sounds.detach()
        self.vc, self.session = None, None
        self.cooldown_until = time.time() + cooldown

    def state_update(self, member, before, after):
        if not self.me or member.id != self.me.id or self.vc is None or self.busy:
            return
        if after.channel is None:
            log.info("she got disconnected from vc")
            self._reset(self.cfg.VOICE_COOLDOWN_MIN * 60 * 2)
        elif before.channel is not None and after.channel.id != before.channel.id:
            log.info("got moved to %s", after.channel.name)

    async def run(self):
        await asyncio.sleep(60)
        while True:
            try:
                if self.active:
                    await (self._maybe_leave() if self.vc is not None else self._maybe_join())
            except Exception:
                log.warning("voice check failed", exc_info=True)
            await asyncio.sleep(self.tick * random.uniform(0.8, 1.2))

    async def _maybe_join(self):
        if not self.can_join():
            return
        now = time.time()
        late = self.app.clock.late
        channels = [
            c
            for g in self.app.her_guilds()
            if not self._away(g.id) and self.app.routine.can_hang_out_in(g.id)
            for c in g.voice_channels
            if joinable(c) and not self.messages.muted(c)
        ]
        random.shuffle(channels)
        for channel in channels:
            ids = self.people(channel)
            if len(ids) < self.cfg.VOICE_MIN_PEOPLE:
                continue
            known = sum(1 for u in ids if str(u) in self.memory.people)
            p = self.cfg.VOICE_JOIN_CHANCE * (1 + 0.4 * min(known, 4))
            if now - self.vc_talk.get(channel.guild.id, 0) < 900:
                p *= 2.5
            if late:
                p *= 0.4
            if random.random() < per_tick(p, self.tick):
                await self.join(channel, f"{len(ids)} people were in there", delay=random.uniform(2, 20))
                return
        solo = self.cfg.VOICE_SOLO_CHANCE
        if solo > 0 and not late and random.random() < per_tick(solo, self.tick):
            empty = [c for c in channels if not self.people(c) and self.app.ambient.chat_active(c.guild)]
            if empty:
                await self.join(random.choice(empty), "felt like hanging out in vc", solo=True)

    async def _maybe_leave(self):
        vc, s = self.vc, self.session
        if not vc.is_connected():
            if s.minutes > 1:
                log.info("lost the voice connection")
                self._reset(self.cfg.VOICE_COOLDOWN_MIN * 60)
            return
        if s.call:
            await self._check_call(vc, s)
            return
        gid = vc.channel.guild.id
        if not self.app.routine.can_hang_out_in(gid):
            await self.leave(f"she's {self.app.routine.doing(gid)}")
            return
        now = time.time()
        ids = self.people(vc.channel)
        s.peak = max(s.peak, len(ids))
        if not ids:
            if s.alone_since is None:
                s.alone_since = now
                waiting_for_people = s.solo and not s.had_company
                s.alone_wait = random.uniform(240, 720) if waiting_for_people else random.uniform(30, 150)
            if now - s.alone_since >= s.alone_wait:
                await self.leave("nobody's there" if s.had_company else "nobody joined")
            return
        s.had_company = True
        s.alone_since = s.alone_wait = None
        lone = ids[0] if len(ids) == 1 else None
        if lone and s.peak >= 2 and str(lone) not in self.memory.people and not s.leave_at:
            s.leave_at = now + random.uniform(60, 300)
        if s.leave_at and now >= s.leave_at:
            await self.leave("the people she came for left")
            return
        if now >= s.stay_until:
            await self._stay_or_go(s, ids, vc.channel.guild.id, now)
            return
        if self.app.clock.late and s.minutes > 20 and random.random() < per_tick(0.5, self.tick):
            await self.leave("it's late")

    async def _stay_or_go(self, s, ids, guild_id, now):
        good = any(self.app.addressing.chatting_with(guild_id, u) for u in ids)
        if good and s.extended < 2:
            s.extended += 1
            s.stay_until = now + random.uniform(5, 20) * 60
        elif random.random() < 0.5:
            await self.leave("been there a while")


def _importable(module):
    try:
        importlib.import_module(module)
    except ImportError:
        return False
    return True
