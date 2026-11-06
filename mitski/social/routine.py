import asyncio
import random
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from mitski.core import logs
from mitski.core.component import Component
from mitski.social.life import LifePlanner

log = logs.get("routine")

ASLEEP = "asleep"
BUSY = "busy"
GAMING = "gaming"
PRIORITY = {ASLEEP: 0, BUSY: 1, GAMING: 2}
PRESENCE = {ASLEEP: "invisible", BUSY: "idle"}

URGENCY = {"dm": 0.4, "ping": 0.6, "chat": 1.0}
OWNER_MAX_WAIT = 300
WAKE_UP_SEC = (60, 1500)
LONGEST_SITTING = 900
KEEP_AROUND_SEC = (60, 180)
TICK = 60
WEEKDAY_BUSY_CHANCE = 0.85
LUNCH_MIN = (30, 60)
ERRAND_MIN = (25, 120)
GAMING_MIN = (30, 150)
ERRANDS_DONE_BY = time(21, 30)
GAMES_DONE_BY = time(23, 45)


@dataclass(frozen=True)
class Spell:
    start: datetime
    end: datetime
    level: str
    what: str

    def covers(self, now):
        return self.start <= now < self.end

    def overlaps(self, other):
        return self.start < other.end and other.start < self.end


@dataclass(frozen=True)
class Week:
    sleep: tuple
    busy: tuple
    busy_what: str
    errands: tuple
    errands_per_day: tuple
    games: tuple
    games_per_day: tuple


def _clock_time(text):
    hours, minutes = str(text).split(":")
    return time(int(hours), int(minutes))


def _span(pair):
    try:
        return (_clock_time(pair[0]), _clock_time(pair[1]))
    except (TypeError, ValueError, IndexError):
        return None


def _place(rng, day, tz, spells, count, what, level, minutes, done_by):
    awake = [s for s in spells if s.level == ASLEEP and s.end.date() == day]
    earliest = awake[0].end if awake else datetime.combine(day, time(9), tz)
    latest = datetime.combine(day, done_by, tz)
    for thing in rng.sample(list(what), min(count, len(what))):
        for _attempt in range(12):
            length = timedelta(minutes=rng.uniform(*minutes))
            room = (latest - earliest - length).total_seconds()
            if room <= 0:
                break
            start = earliest + timedelta(seconds=rng.uniform(0, room))
            spell = Spell(start, start + length, level, thing)
            if not any(spell.overlaps(s) for s in spells):
                spells.append(spell)
                break


def plan_day(day, week, tz, seed=""):
    """One day of her life. The same day always comes out the same, so a restart doesn't change her plans."""
    rng = random.Random(f"{seed}:{day.isoformat()}")
    weekend = day.weekday() >= 5
    spells = []

    def at(clock, jitter):
        return datetime.combine(day, clock, tz) + timedelta(minutes=rng.uniform(-jitter, jitter))

    if week.sleep:
        start, end = at(week.sleep[0], 40), at(week.sleep[1], 40)
        if end <= start:
            end += timedelta(days=1)
        if weekend:
            start, end = start + timedelta(minutes=45), end + timedelta(minutes=rng.uniform(30, 120))
        spells.append(Spell(start, end, ASLEEP, "asleep"))
    if week.busy and not weekend and rng.random() < WEEKDAY_BUSY_CHANCE:
        start, end = at(week.busy[0], 30), at(week.busy[1], 30)
        lunch = start + (end - start) * rng.uniform(0.4, 0.6)
        back = lunch + timedelta(minutes=rng.uniform(*LUNCH_MIN))
        if start < lunch and back < end:
            spells.append(Spell(start, lunch, BUSY, week.busy_what))
            spells.append(Spell(back, end, BUSY, week.busy_what))
    _place(rng, day, tz, spells, rng.randint(*week.errands_per_day), week.errands, BUSY, ERRAND_MIN, ERRANDS_DONE_BY)
    _place(rng, day, tz, spells, rng.randint(*week.games_per_day), week.games, GAMING, GAMING_MIN, GAMES_DONE_BY)
    return sorted(spells, key=lambda s: s.start)


class Routine(Component):
    def __init__(self, app):
        super().__init__(app)
        cfg = app.cfg
        self.on = cfg.ROUTINE
        self.week = Week(
            sleep=_span(cfg.ROUTINE_SLEEP),
            busy=_span(cfg.ROUTINE_BUSY),
            busy_what=str(cfg.ROUTINE_BUSY_WHAT),
            errands=tuple(cfg.ROUTINE_ERRANDS),
            errands_per_day=tuple(cfg.ROUTINE_ERRANDS_PER_DAY),
            games=tuple(cfg.ROUTINE_GAMES),
            games_per_day=tuple(cfg.ROUTINE_GAMES_PER_DAY),
        )
        self.planner = LifePlanner(app, on_change=self._replanned)
        self.days = {}
        self.forced = None
        self.free_until = 0.0
        self.around_until = 0.0
        self.sat_down = 0.0
        self.next_look = 0.0
        self.last = ()

    def now(self):
        return self.app.clock.now()

    def stamp(self):
        return self.now().timestamp()

    def _day(self, day, tz):
        if day not in self.days:
            self.days = {d: plans for d, plans in self.days.items() if abs((d - day).days) <= 2}
            planned = self.planner.spells(day, tz)
            if planned is not None:
                self.days[day] = [Spell(*s) for s in planned]
            else:
                self.days[day] = plan_day(day, self.week, tz, self.cfg.OWNER_ID)
        return self.days[day]

    def _replanned(self, day):
        self.days.pop(day, None)
        if day == self.now().date():
            self.last = ()

    def redo(self):
        if not self.on:
            return "routine is off, `ROUTINE: true` first"
        if not self.planner.on:
            return "her model doesn't plan her days, `ROUTINE_PLANNER: true` first"
        now = self.now()
        self.planner.redo(now.date())
        self.planner.ensure(now)
        return "planning her day again, ask for her routine again in a minute or two"

    def awake_here(self, guild_id):
        """Servers she's set never to sleep in (SLEEP_EXCLUDE, !sleepexclude) ignore her routine's sleep too."""
        if guild_id is None:
            return False
        away = getattr(self.app, "away", None)
        exclude = away.exclude if away is not None else self.cfg.sleep_exclude
        return int(guild_id) in exclude

    def spell(self, now=None, guild_id=None):
        spell = self._spell(now)
        if spell is not None and spell.level == ASLEEP and self.awake_here(guild_id):
            return None
        return spell

    def _spell(self, now=None):
        if not self.on:
            return None
        now = now or self.now()
        if self.forced is not None:
            if now < self.forced.end:
                return self.forced
            self.forced = None
        if now.timestamp() < self.free_until:
            return None
        spells = [
            s
            for offset in (-1, 0, 1)
            for s in self._day(now.date() + timedelta(days=offset), now.tzinfo)
            if s.covers(now)
        ]
        return min(spells, key=lambda s: PRIORITY[s.level]) if spells else None

    @property
    def free(self):
        return self.spell() is None

    @property
    def level(self):
        spell = self.spell()
        return spell.level if spell else None

    @property
    def can_hang_out(self):
        return self.level in (None, GAMING)

    def free_in(self, guild_id):
        return self.spell(guild_id=guild_id) is None

    def level_in(self, guild_id):
        spell = self.spell(guild_id=guild_id)
        return spell.level if spell else None

    def can_hang_out_in(self, guild_id):
        return self.level_in(guild_id) in (None, GAMING)

    def doing(self, guild_id=None):
        spell = self.spell(guild_id=guild_id)
        return spell.what if spell else ""

    def looking(self, guild_id=None):
        return self.free_in(guild_id) or self.stamp() < self.around_until

    def _look_gap(self, spell):
        low, high = self.cfg.ROUTINE_LOOK_GAMING if spell.level == GAMING else self.cfg.ROUTINE_LOOK_BUSY
        return random.uniform(low, high)

    def look(self):
        spell, t = self.spell(), self.stamp()
        if spell is None:
            return
        self.sat_down = t
        self.around_until = t + random.uniform(*self.cfg.ROUTINE_STAY)
        self.next_look = self.around_until + self._look_gap(spell)

    def keep_around(self):
        t = self.stamp()
        if t < self.around_until:
            longest = self.sat_down + LONGEST_SITTING
            self.around_until = min(max(self.around_until, t + random.uniform(*KEEP_AROUND_SEC)), longest)

    def notice_at(self, kind, owner=False, guild_id=None):
        spell, t = self.spell(guild_id=guild_id), self.stamp()
        if spell is None:
            return t
        if owner and spell.level == ASLEEP:
            return t + random.uniform(60, OWNER_MAX_WAIT)
        if spell.level == ASLEEP:
            return spell.end.timestamp() + random.uniform(*WAKE_UP_SEC)
        if self.next_look <= t:
            self.next_look = t + self._look_gap(spell)
        wait = (self.next_look - t) * URGENCY[kind] * random.uniform(0.7, 1.3)
        return t + (min(wait, OWNER_MAX_WAIT) if owner else wait)

    def status(self):
        if self.cfg.ROUTINE_PRESENCE:
            level = self.level
            if level in PRESENCE:
                return PRESENCE[level]
        return self.cfg.STATUS

    def note(self, guild_id=None):
        spell = self.spell(guild_id=guild_id)
        if spell is None:
            return self.planner.today_note(self.now()) if self.on else ""
        if spell.level == ASLEEP:
            return "You were asleep and this just woke you up, so you're groggy and keep it short."
        return f"Right now you're {spell.what}, so you're only half here and keep it short."

    def seen_late(self, seconds, what):
        minutes = round(seconds / 60)
        how_long = f"about {round(minutes / 60)} hours" if minutes >= 90 else f"about {minutes} minutes"
        return (
            f"You only just saw this, {how_long} after they sent it, because you were {what}. Only bring that up if "
            f"it fits, no big apology."
        )

    def set_busy(self, minutes, what="busy"):
        now = self.now()
        self.free_until = 0.0
        self.forced = Spell(now, now + timedelta(minutes=minutes), BUSY, what)

    def set_free(self, minutes):
        self.forced = None
        self.free_until = self.stamp() + minutes * 60

    def listing(self):
        if not self.on:
            return "**routine: off**"
        now = self.now()
        rows = [
            f"{s.start:%H:%M}-{s.end:%H:%M} {s.level}: {s.what}"
            for offset in (0, 1)
            for s in self._day(now.date() + timedelta(days=offset), now.tzinfo)
            if s.end > now and s.start < now + timedelta(hours=24)
        ]
        spell = self.spell()
        state = f"{spell.what} until {spell.end:%H:%M}" if spell else "free"
        if not self.planner.on:
            source = "simple plan from the config"
        elif self.planner.planned(now.date()):
            source = "planned by her model"
        else:
            source = "simple plan for now, her model is still planning today"
        about = "".join(f"\n{line}" for line in self.planner.describe(now.date())) if self.planner.on else ""
        return f"**routine: on** ({source}), right now {state}{about}\nnext 24 hours:\n" + (
            "\n".join(rows) or "nothing planned"
        )

    async def _changed(self, spell):
        self.around_until = 0.0
        self.next_look = 0.0
        text = f"**{spell.level}** {spell.what} until {spell.end:%H:%M}" if spell else "**free** again"
        log.info("%s", text.replace("*", ""))
        await self.app.relay.post(text)
        await self.app.profiles.apply()
        if spell is not None and spell.level != GAMING:
            for guild in self.app.her_guilds():
                if spell.level == ASLEEP and self.awake_here(guild.id):
                    continue
                if not self.app.away.state(guild.id):
                    await self.app.sleep.say_bye(guild)

    async def tick(self):
        if self.on:
            self.planner.ensure(self.now())
        spell = self.spell()
        key = (spell.start, spell.what) if spell else None
        if key == self.last:
            return
        first, self.last = self.last == (), key
        if first:
            if spell is not None:
                await self.app.profiles.apply()
            return
        await self._changed(spell)

    async def run(self):
        while True:
            try:
                await self.tick()
            except Exception:
                log.warning("routine check failed", exc_info=True)
            await asyncio.sleep(TICK)
