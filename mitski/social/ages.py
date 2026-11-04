import asyncio
import random
import re
import time
from collections import deque
from dataclasses import dataclass

import discord

from mitski.core import logs
from mitski.core.collections import BoundedDict, window_count
from mitski.core.component import Component
from mitski.core.storage import JsonFile

log = logs.get("ages")

MINOR_AGE = re.compile(
    r"(?<![\d.+])(1[0-7])\s*(?:y/?o\b|yo\b|yrs?\b|years?(?:\s+old)?\b|m\b|f\b|\+)|"
    r"\b(?:age|aged|im|i'm|i am)\s*[:=-]?\s*(1[0-7])(?![\d.+])|"
    r"(?:^|[|•·/,\n(\[{])\s*(1[0-7])\s*(?=$|[|•·/,\n)\]}])",
    re.I,
)
MINOR_RANGE = re.compile(r"(?<![\d.])(1[0-7])\s*[-–~]\s*(1[0-8])(?![\d+])")
MINOR_WORDS = re.compile(
    r"\b(?:minor|underage|under\s*age|under\s*18|u18|not\s*18|sub\s*18|below\s*18|middle\s*school|"
    r"high\s*school(?:er)?|freshman|sophomore|year\s*(?:7|8|9|10|11)|grade\s*(?:[5-9]|1[0-2]))\b|"
    r"(?<![\d+])[-<]\s*18\b|\b18\s*-(?!\s*\d)",
    re.I,
)
PROFILE_TTL = 24 * 3600
HOUR = 3600


@dataclass(frozen=True)
class Signal:
    age: int | None
    why: str


def read_signal(text, where):
    text = str(text or "").strip()
    if not text:
        return None
    m = MINOR_RANGE.search(text)
    if m:
        return Signal(int(m.group(1)), f'{where} says "{m.group(0).strip()}"')
    m = MINOR_AGE.search(text)
    if m:
        age = next(int(g) for g in m.groups() if g)
        return Signal(age, f'{where} says "{m.group(0).strip(" |•·/,([{)]}")}"')
    m = MINOR_WORDS.search(text)
    if m:
        return Signal(None, f'{where} says "{m.group(0).strip()}"')
    return None


def strongest(signals):
    found = [s for s in signals if s is not None]
    if not found:
        return None
    with_age = [s for s in found if s.age is not None]
    return min(with_age, key=lambda s: s.age) if with_age else found[0]


class AgeGuard(Component):
    def __init__(self, app):
        super().__init__(app)
        self.file = JsonFile(app.cfg.paths.data_file("age_flags.json"))
        self.flags = {}
        self.role_seen = BoundedDict(5000)
        self.profile_seen = BoundedDict(5000)
        self.fetch_times = deque()
        self.fetch_lock = asyncio.Lock()
        self.pending = {}

    def load(self):
        self.flags = {k: v for k, v in self.file.load().items() if isinstance(v, dict)}

    def save(self):
        self.file.save(self.flags)

    def flag_of(self, uid):
        found = self.flags.get(str(uid)) or {}
        return strongest([Signal(v.get("age"), v.get("why", "")) for v in found.values()])

    def is_minor(self, user_or_id):
        uid = getattr(user_or_id, "id", user_or_id)
        if uid is None:
            return False
        if self.flag_of(uid) is not None:
            return True
        d = self.memory.get(uid)
        age = self.memory.current_age(d) if d else None
        return age is not None and age < 18

    def any_minor(self, users_or_ids):
        return any(self.is_minor(u) for u in users_or_ids if u is not None)

    def describe(self, user):
        flag = self.flag_of(getattr(user, "id", user))
        if flag is None:
            return ""
        return f"{flag.age}" if flag.age is not None else "under 18"

    def check_member(self, user):
        if not self.cfg.AGE_CHECK or user is None or getattr(user, "bot", False):
            return
        roles = [r.name for r in getattr(user, "roles", None) or [] if not r.is_default()]
        names = [getattr(user, a, None) for a in ("display_name", "global_name", "nick")]
        key = (tuple(roles), tuple(n for n in names if n))
        if self.role_seen.get(user.id) == key:
            return
        self.role_seen[user.id] = key
        signal = strongest([read_signal(r, f"their role {r!r}") for r in roles])
        self._apply(user, "roles", signal)
        name_signal = strongest([read_signal(n, "their name") for n in names if n])
        self._apply(user, "name", name_signal)

    def want_profile(self, user):
        if not (self.cfg.AGE_CHECK and self.cfg.AGE_CHECK_BIOS) or getattr(user, "bot", False):
            return False
        if not callable(getattr(user, "profile", None)):
            return False
        seen = self.profile_seen.get(user.id)
        return seen is None or time.time() - seen > PROFILE_TTL

    def look_up(self, user):
        if user.id in self.pending or not self.want_profile(user):
            return
        task = self.app.tasks.spawn(self.check_profile(user), name=f"profile-{user.id}")
        self.pending[user.id] = task
        task.add_done_callback(lambda _t, uid=user.id: self.pending.pop(uid, None))

    async def settled(self, user, timeout=8.0):
        task = self.pending.get(getattr(user, "id", None))
        if task is not None:
            await asyncio.wait({task}, timeout=timeout)

    async def check_profile(self, user):
        if not self.want_profile(user):
            return
        async with self.fetch_lock:
            if not self.want_profile(user):
                return
            if window_count(self.fetch_times, HOUR, time.monotonic()) >= self.cfg.AGE_CHECK_BIOS_PER_HOUR:
                return
            self.profile_seen[user.id] = time.time()
            self.fetch_times.append(time.monotonic())
            try:
                profile = await user.profile()
            except (discord.HTTPException, TypeError, AttributeError) as e:
                log.debug("couldn't read %s's profile: %r", user, e)
                return
            finally:
                await asyncio.sleep(random.uniform(2, 5))
        bios = [getattr(profile, a, None) for a in ("bio", "guild_bio")]
        self._apply(user, "bio", strongest([read_signal(b, "their bio") for b in bios if b]))

    def _apply(self, user, source, signal):
        key = str(user.id)
        current = self.flags.get(key, {})
        if signal is None:
            if source in current:
                current.pop(source)
                if not current:
                    self.flags.pop(key, None)
                self.save()
                log.info("%s: the %s no longer says they're under 18", user, source)
            return
        entry = {"age": signal.age, "why": signal.why, "t": time.time()}
        if current.get(source, {}).get("why") == entry["why"]:
            return
        self.flags.setdefault(key, {})[source] = entry
        self.save()
        log.info("%s: treating them as a minor, %s", user, signal.why)
        if signal.age is not None:
            self.memory.note_age(user, signal.age, signal.why)
