import random
import re
import time

from mitski.core import logs
from mitski.core.clock import DAY, per_tick
from mitski.core.storage import JsonFile

log = logs.get("away")

ALL = "*"
UNQUIET = re.compile(
    r"\b(?:you|u|ya)\s*(?:can|may|are allowed to|r allowed to)\s+(?:talk|speak|chat|type)(?:\s+(?:again|now))?\b|"
    r"\b(?:stop being quiet|no more quiet|unquiet|unmute|talk again|speak again)\b",
    re.I,
)


class Away:
    def __init__(self, cfg, exclude=None):
        self.sleep_on = cfg.SLEEP_MODE
        self.chance = cfg.SLEEP_CHANCE
        hours = cfg.SLEEP_HOURS or [1.5, 4]
        self.hours = (float(hours[0]), float(hours[-1]))
        self.max_day = cfg.SLEEP_MAX_PER_DAY
        self.night_boost = cfg.SLEEP_NIGHT_BOOST
        self.bye_chance = cfg.SLEEP_BYE_CHANCE
        self.tick = cfg.SLEEP_CHECK_SEC
        self.exclude = exclude if exclude is not None else set()
        self.file = JsonFile(cfg.paths.data_file("away.json"), {"quiet": {}, "sleep": {}, "naps": {}})
        self.data = {"quiet": {}, "sleep": {}, "naps": {}}
        self.woke = {}
        self.released = {}

    def load(self, legacy_quiet_until=0):
        saved = self.file.load()
        for k in self.data:
            if isinstance(saved.get(k), dict):
                self.data[k] = saved[k]
        if legacy_quiet_until and legacy_quiet_until > time.time() and ALL not in self.data["quiet"]:
            self.data["quiet"][ALL] = legacy_quiet_until
            self.save()

    def save(self):
        self.file.save(self.data)

    @staticmethod
    def _key(gid):
        return ALL if gid in (None, ALL) else str(gid)

    def quiet(self, gid, minutes):
        key = self._key(gid)
        if minutes and float(minutes) > 0:
            self.data["quiet"][key] = time.time() + float(minutes) * 60
        else:
            self.data["quiet"].pop(key, None)
        self.save()

    def unquiet(self, gid=None):
        changed = self.data["quiet"].pop(ALL, None) is not None
        if gid not in (None, ALL):
            changed = self.data["quiet"].pop(str(gid), None) is not None or changed
        if changed:
            self.released[str(gid)] = time.time()
            self.save()
        return changed

    def unquiet_everywhere(self):
        self.data["quiet"].clear()
        self.save()

    def quiet_until(self, gid):
        q = self.data["quiet"]
        until = max(q.get(ALL, 0), q.get(str(gid), 0) if gid not in (None, ALL) else 0)
        return until if until > time.time() else 0

    def is_quiet(self, gid):
        return bool(self.quiet_until(gid))

    def quiet_left(self, gid):
        until = self.quiet_until(gid)
        return max(1, int((until - time.time()) // 60) + 1) if until else 0

    def sleep(self, gid, hours, why=""):
        now = time.time()
        self.data["sleep"][str(gid)] = {"since": now, "until": now + float(hours) * 3600, "why": why}
        naps = [t for t in self.data["naps"].get(str(gid), []) if now - t < DAY]
        self.data["naps"][str(gid)] = naps + [now]
        self.save()

    def wake(self, gid):
        if self.data["sleep"].pop(str(gid), None) is None:
            return False
        self.woke[str(gid)] = time.time()
        self.save()
        return True

    def asleep(self, gid):
        s = self.data["sleep"].get(str(gid))
        return bool(s) and time.time() < s["until"]

    def sleep_left(self, gid):
        s = self.data["sleep"].get(str(gid))
        return max(0, int((s["until"] - time.time()) // 60)) if s else 0

    def state(self, gid):
        if gid is None:
            return None
        if self.is_quiet(gid):
            return "quiet"
        if self.asleep(gid):
            return "asleep"
        return None

    def ended(self):
        now = time.time()
        done = [g for g, s in self.data["sleep"].items() if now >= s["until"]]
        for g in done:
            self.data["sleep"].pop(g, None)
            self.woke[g] = now
        expired = [g for g, t in self.data["quiet"].items() if now >= t]
        for g in expired:
            self.data["quiet"].pop(g, None)
        if done or expired:
            self.save()
        return [int(g) for g in done]

    def just_woke(self, gid, within=600):
        t = self.woke.pop(str(gid), None)
        return t is not None and time.time() - t < within

    def just_released(self, gid, within=600):
        t = self.released.pop(str(gid), None)
        return t is not None and time.time() - t < within

    def naps_today(self, gid):
        return sum(1 for t in self.data["naps"].get(str(gid), []) if time.time() - t < DAY)

    def wants_nap(self, gid, late, rng=random):
        if not self.sleep_on or int(gid) in self.exclude or self.state(gid) is not None:
            return False
        if self.naps_today(gid) >= self.max_day:
            return False
        p = self.chance * (self.night_boost if late else 1.0)
        return rng.random() < per_tick(p, self.tick)

    def nap_hours(self, late, rng=random):
        h = rng.uniform(*self.hours)
        return min(h * 1.6, self.hours[1] * 2) if late else h

    def listing(self, label):
        asleep = [f"{label(int(g))}: {self.sleep_left(g) / 60:.1f}h left" for g in self.data["sleep"] if self.asleep(g)]
        quiet = [
            ("every server" if g == ALL else label(int(g))) + f": {self.quiet_left(g)} min left"
            for g in self.data["quiet"]
            if self.is_quiet(g)
        ]
        return (
            f"**sleep mode: {'on' if self.sleep_on else 'off'}**\n"
            f"never sleeps in: {', '.join(label(g) for g in sorted(self.exclude)) or 'nowhere excluded'}\n"
            f"asleep: {', '.join(asleep) or 'nowhere'}\n"
            f"quiet: {', '.join(quiet) or 'nowhere'}"
        )
