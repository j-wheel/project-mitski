import asyncio
import time

from mitski.core import logs
from mitski.core.component import Component
from mitski.social.routine import ASLEEP

log = logs.get("downtime")

TICK = 60


class Downtime(Component):
    def __init__(self, app):
        super().__init__(app)
        self.waiting = {}
        self.done = 0
        self.overdue = 0
        self.working = ""
        self.started = time.monotonic()

    @property
    def on(self):
        return bool(self.cfg.DOWNTIME)

    def resting(self):
        routine = getattr(self.app, "routine", None)
        if routine is not None and routine.level == ASLEEP:
            return "asleep"
        guilds = self.app.her_guilds()
        if guilds and all(self.app.away.asleep(g.id) for g in guilds):
            return "asleep"
        quiet_for = time.monotonic() - max(self.app.gpu.last_busy, self.started)
        if quiet_for >= self.cfg.DOWNTIME_IDLE_MIN * 60:
            return "idle"
        return ""

    def later(self, key, make, what):
        if not self.on:
            self.app.tasks.spawn(make(), name=key)
            return
        if key not in self.waiting:
            self.waiting[key] = (time.time(), make, what)
            log.debug("saved for later: %s", what)

    def _next(self):
        if not self.waiting:
            return None, ""
        key = min(self.waiting, key=lambda k: self.waiting[k][0])
        if time.time() - self.waiting[key][0] >= self.cfg.DOWNTIME_MAX_WAIT_H * 3600:
            return key, "waited too long"
        why = self.resting()
        return (key, why) if why else (None, "")

    async def tick(self):
        if self.working:
            return
        key, why = self._next()
        if key is None:
            return
        since, make, what = self.waiting.pop(key)
        self.working = what
        self.overdue += why == "waited too long"
        log.info("%s (%s, waited %d min)", what, why, (time.time() - since) // 60)
        try:
            await make()
        except Exception:
            log.warning("%s failed", what, exc_info=True)
        finally:
            self.working = ""
            self.done += 1

    async def run(self):
        while True:
            await asyncio.sleep(TICK)
            try:
                await self.tick()
            except Exception:
                log.warning("downtime check failed", exc_info=True)

    def report(self):
        if not self.on:
            return "downtime: off, memory work runs right away"
        why = self.resting()
        state = f"resting ({why})" if why else "busy"
        doing = f", doing: {self.working}" if self.working else ""
        late = f", {self.overdue} ran anyway after {self.cfg.DOWNTIME_MAX_WAIT_H}h" if self.overdue else ""
        return f"downtime: {state}, {len(self.waiting)} jobs waiting, {self.done} done{late}{doing}"
