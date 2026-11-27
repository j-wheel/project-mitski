import random
import re
import time as monotonic
from datetime import date, datetime, time, timedelta

from mitski.chat.messages import short_name
from mitski.core import logs
from mitski.core.component import Component
from mitski.core.storage import JsonFile
from mitski.core.text import cut, squash
from mitski.core.texts import say, wording
from mitski.llm import gpu
from mitski.social import games

log = logs.get("life")

HHMM = re.compile(r"^\s*([01]?\d|2[0-3])[:.h]([0-5]\d)\s*$")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
PHASES = ("term", "exams", "break")
EARLIEST_WAKE, LATEST_WAKE = time(5, 0), time(13, 30)
EARLIEST_BED, LATEST_BED = time(20, 30), time(4, 0)
SLEEP_HOURS = (5.0, 11.0)
LONGEST_HOURS = {"busy": 10, "gaming": 6}
TRIP_LONGEST_HOURS = 15
WEEKLY_HOURS = (time(7, 0), time(22, 0))
WEEKLY_MAX_HOURS = 35
MAX_SPELLS = 12
RETRY_SEC = 1800
TERM_RECHECK_DAYS = 7
KEEP_DAYS = 14
KEEP_WEEKS = 8
KEEP_TRIP_DAYS = 180
PLAN_TOMORROW_FROM = 17

OFF_LIMITS = re.compile(
    r"\b(pregnan\w*|baby|babies|abortion|miscarriage|wedding|married|marry|marrying|engaged|engagement|divorce\w*|"
    r"boyfriend|girlfriend|first date|date with|"
    r"ferrari|lamborghini|porsche|bugatti|mclaren|bentley|rolex|yacht|mansion|private jet|first class|designer bag|"
    r"lottery|jackpot|casino|inherit\w*|millions?|"
    r"hospital|surgery|emergency room|ambulance|cancer|funeral|died|dies|death|"
    r"arrest\w*|police|jail|prison|lawsuit|"
    r"fired|expelled|drop(?:s|ped|ping)? out|quit(?:s|ting)? (?:uni|university|school|her degree|her course|her job)|"
    r"moving (?:out|to|abroad|house)|new apartment|new flat|buy(?:s|ing)? a (?:car|house|flat|apartment)|"
    r"tattoo|rehab|drugs?|weed|cocaine)\b",
    re.I,
)
TRAVEL = re.compile(
    r"\b(flight|flying|airport|plane|abroad|trip|travel\w*|vacation|holiday in|hotel|hostel|airbnb|interrail|"
    r"(?:train|bus|drive|driving|ferry) to)\b",
    re.I,
)

_TIME = {"type": "string", "maxLength": 5}
_DATE = {"type": "string", "maxLength": 10}
TERM_SCHEMA = {
    "type": "object",
    "properties": {
        "phase": {"enum": list(PHASES)},
        "until": _DATE,
        "semester": {"type": "string", "maxLength": 20},
        "holidays": {
            "type": "array",
            "maxItems": 10,
            "items": {
                "type": "object",
                "properties": {"date": _DATE, "name": {"type": "string", "maxLength": 60}},
                "required": ["date", "name"],
                "additionalProperties": False,
            },
        },
        "note": {"type": "string", "maxLength": 200},
    },
    "required": ["phase", "until", "semester", "holidays", "note"],
    "additionalProperties": False,
}
WEEKLY_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "maxItems": 25,
            "items": {
                "type": "object",
                "properties": {
                    "day": {"enum": list(WEEKDAYS)},
                    "from": _TIME,
                    "to": _TIME,
                    "what": {"type": "string", "maxLength": 60},
                },
                "required": ["day", "from", "to", "what"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}
WEEK_SCHEMA = {
    "type": "object",
    "properties": {
        "plans": {
            "type": "array",
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {"date": _DATE, "what": {"type": "string", "maxLength": 80}},
                "required": ["date", "what"],
                "additionalProperties": False,
            },
        },
        "trip_where": {"type": "string", "maxLength": 60},
        "trip_why": {"type": "string", "maxLength": 80},
    },
    "required": ["plans", "trip_where", "trip_why"],
    "additionalProperties": False,
}
DAY_SCHEMA = {
    "type": "object",
    "properties": {
        "wake": _TIME,
        "spells": {
            "type": "array",
            "maxItems": MAX_SPELLS,
            "items": {
                "type": "object",
                "properties": {
                    "from": _TIME,
                    "to": _TIME,
                    "level": {"enum": ["busy", "gaming"]},
                    "what": {"type": "string", "maxLength": 60},
                    "game": {"type": "string", "maxLength": 40},
                },
                "required": ["from", "to", "level", "what", "game"],
                "additionalProperties": False,
            },
        },
        "bed": _TIME,
        "up_next_day": _TIME,
        "summary": {"type": "string", "maxLength": 160},
    },
    "required": ["wake", "spells", "bed", "up_next_day", "summary"],
    "additionalProperties": False,
}
LIMITS = wording("life.limits")


def clock_time(text):
    found = HHMM.match(str(text or ""))
    return time(int(found.group(1)), int(found.group(2))) if found else None


def iso_date(text):
    try:
        return date.fromisoformat(str(text or "")[:10])
    except ValueError:
        return None


def tidy_what(text):
    text = squash(text).strip(" .!,;:-\"'").lower()
    text = re.sub(r"^(she'?s|she is|you'?re|you are|i'?m|i am)\s+", "", text)
    return text[:60].rstrip() if len(text) >= 3 else ""


def allowed(text, trip=False):
    return bool(text) and not OFF_LIMITS.search(text) and (trip or not TRAVEL.search(text))


def build_day(day, tz, raw, wake=None, trip=False, morning=True, played=()):
    if not isinstance(raw, dict):
        return None
    wake = wake or clock_time(raw.get("wake"))
    bed, up = clock_time(raw.get("bed")), clock_time(raw.get("up_next_day"))
    if wake is None or bed is None or up is None:
        return None
    wake = min(max(wake, EARLIEST_WAKE), LATEST_WAKE)
    start = datetime.combine(day, wake, tz)

    def when(t):
        at = datetime.combine(day, t, tz)
        return at + timedelta(days=1) if t < wake else at

    tomorrow = day + timedelta(days=1)
    night = min(max(when(bed), datetime.combine(day, EARLIEST_BED, tz)), datetime.combine(tomorrow, LATEST_BED, tz))
    hours = (datetime.combine(tomorrow, up, tz) - night).total_seconds() / 3600
    up_at = night + timedelta(hours=min(max(hours, SLEEP_HOURS[0]), SLEEP_HOURS[1]))
    up_at = min(max(up_at, datetime.combine(tomorrow, EARLIEST_WAKE, tz)), datetime.combine(tomorrow, LATEST_WAKE, tz))

    spells, dropped = [], []
    for item in (raw.get("spells") or [])[: MAX_SPELLS * 2]:
        if not isinstance(item, dict):
            continue
        what, level = tidy_what(item.get("what")), str(item.get("level") or "").lower()
        a, b = clock_time(item.get("from")), clock_time(item.get("to"))
        if level not in LONGEST_HOURS or a is None or b is None or not what:
            continue
        if not allowed(what, trip):
            dropped.append(what)
            continue
        s, e = max(when(a), start), min(when(b), night)
        longest = TRIP_LONGEST_HOURS if trip and level == "busy" else LONGEST_HOURS[level]
        if timedelta(minutes=10) <= e - s <= timedelta(hours=longest):
            game = ""
            if level == "gaming":
                named = str(item.get("game") or "").strip()
                game = next((g for g in played if g.lower() == named.lower()), "") or games.match(
                    f"{named} {what}", played
                )
            spells.append((s, e, level, what, game))
    kept = []
    for s in sorted(spells, key=lambda s: s[0]):
        if not kept or s[0] >= kept[-1][1]:
            kept.append(s)
    out = [(datetime.combine(day, time(0, 0), tz), start, "asleep", "asleep", "")] if morning else []
    out += kept[:MAX_SPELLS] + [(night, up_at, "asleep", "asleep", "")]
    summary = squash(raw.get("summary"))[:160]
    return {
        "wake": wake.strftime("%H:%M"),
        "up_next": up_at.strftime("%H:%M"),
        "summary": summary if allowed(summary, trip) else "",
        "spells": [[a.isoformat(), b.isoformat(), level, what, game] for a, b, level, what, game in out],
        "dropped": dropped,
    }


def check_weekly(raw):
    items = []
    for item in (raw or {}).get("items") or []:
        if not isinstance(item, dict) or item.get("day") not in WEEKDAYS:
            continue
        a, b, what = clock_time(item.get("from")), clock_time(item.get("to")), tidy_what(item.get("what"))
        if a is None or b is None or not allowed(what) or not WEEKLY_HOURS[0] <= a < b <= WEEKLY_HOURS[1]:
            continue
        minutes = (b.hour * 60 + b.minute) - (a.hour * 60 + a.minute)
        if 30 <= minutes <= 300:
            items.append({"day": item["day"], "from": a.strftime("%H:%M"), "to": b.strftime("%H:%M"), "what": what})
    items.sort(key=lambda i: (WEEKDAYS.index(i["day"]), i["from"]))
    kept, total = [], 0
    for i in items:
        if kept and kept[-1]["day"] == i["day"] and i["from"] < kept[-1]["to"]:
            continue
        a, b = clock_time(i["from"]), clock_time(i["to"])
        total += (b.hour * 60 + b.minute) - (a.hour * 60 + a.minute)
        if total > WEEKLY_MAX_HOURS * 60:
            break
        kept.append(i)
    return kept


def trip_dates(week_start, seed, chance, gap_weeks, days, last_end, phase):
    if phase == "exams" or chance <= 0:
        return None
    if last_end is not None and (week_start - last_end).days < gap_weeks * 7:
        return None
    rng = random.Random(f"{seed}:trip:{week_start.isoformat()}")
    if rng.random() >= chance:
        return None
    low, high = (max(1, int(d)) for d in (list(days) + [1, 1])[:2])
    length = min(rng.randint(min(low, high), max(low, high)), 7)
    if phase == "break":
        first = week_start + timedelta(days=rng.randint(0, 7 - length))
    else:
        first = week_start + timedelta(days=rng.choice((4, 5)))
    return first, first + timedelta(days=length - 1)


class LifePlanner(Component):
    def __init__(self, app, on_change=None):
        super().__init__(app)
        self.file = JsonFile(app.cfg.paths.data_file("routine.json"))
        self.data = None
        self.on_change = on_change or (lambda day: None)
        self.running = set()
        self.retry_at = {}

    @property
    def on(self):
        return bool(self.cfg.ROUTINE and self.cfg.ROUTINE_PLANNER)

    @property
    def place(self):
        return str(self.cfg.ROUTINE_PLACE or "").strip()

    def _store(self):
        if self.data is None:
            loaded = self.file.load()
            self.data = loaded if isinstance(loaded, dict) else {}
            for key, empty in (("days", {}), ("weeks", {}), ("trips", []), ("weekly", {}), ("term", {})):
                if not isinstance(self.data.get(key), type(empty)):
                    self.data[key] = empty
        return self.data

    def _save(self, today):
        data = self._store()
        data["days"] = {k: v for k, v in data["days"].items() if (today - date.fromisoformat(k)).days <= KEEP_DAYS}
        data["weeks"] = {
            k: v for k, v in data["weeks"].items() if (today - date.fromisoformat(k)).days <= KEEP_WEEKS * 7
        }
        data["trips"] = [t for t in data["trips"] if (today - date.fromisoformat(t["end"])).days <= KEEP_TRIP_DAYS]
        self.file.save(data)

    def spells(self, day, tz):
        if not self.on:
            return None
        plan = self._store()["days"].get(day.isoformat())
        if not plan:
            return None
        out = []
        for a, b, level, what, *rest in plan["spells"]:
            game = rest[0] if rest else (games.match(what, self.cfg.ROUTINE_GAMES) if level == "gaming" else "")
            start, end = datetime.fromisoformat(a).astimezone(tz), datetime.fromisoformat(b).astimezone(tz)
            out.append((start, end, level, what, game))
        return out

    def planned(self, day):
        return day.isoformat() in self._store()["days"]

    def trip_on(self, day):
        for t in self._store()["trips"]:
            if t["start"] <= day.isoformat() <= t["end"]:
                return t
        return None

    def today_note(self, now):
        if not self.on:
            return ""
        plan = self._store()["days"].get(now.date().isoformat()) or {}
        parts = [say("life.plans_today", summary=plan["summary"])] if plan.get("summary") else []
        trip = self.trip_on(now.date())
        if trip:
            parts.append(
                say(
                    "life.away_until",
                    where=trip["where"],
                    why=trip["why"],
                    until=format(date.fromisoformat(trip["end"]), "%A"),
                )
            )
        return " ".join(parts)

    def describe(self, today):
        data = self._store()
        term, lines = data["term"], []
        if term:
            lines.append(f"{term['phase']} until {term['until']}" + (f", {term['note']}" if term.get("note") else ""))
        plan = data["days"].get(today.isoformat())
        if plan:
            lines.append(f"today: {plan['summary'] or 'planned'}")
        trip = self.trip_on(today) or next((t for t in data["trips"] if t["start"] > today.isoformat()), None)
        if trip:
            lines.append(f"trip: {trip['where']} ({trip['why']}), {trip['start']} to {trip['end']}")
        return lines

    def redo(self, today):
        data = self._store()
        for key in [k for k in data["days"] if k >= today.isoformat()]:
            del data["days"][key]
            self.retry_at.pop(key, None)
            self.on_change(date.fromisoformat(key))
        self._save(today)

    def ensure(self, now):
        if not self.on or self.running or getattr(self.app, "tasks", None) is None:
            return
        today = now.date()
        wanted = [today] + ([today + timedelta(days=1)] if now.hour >= PLAN_TOMORROW_FROM else [])
        for day in wanted:
            key = day.isoformat()
            if self.planned(day):
                continue
            if self.retry_at.get(key, 0) > monotonic.monotonic():
                return
            self.running.add(key)
            self.app.tasks.spawn(self._plan(day, now.tzinfo), name=f"plan-{key}")
            return

    async def _plan(self, day, tz):
        key = day.isoformat()
        gpu.background()
        ok = False
        try:
            ok = await self.plan_day(day, tz)
        except Exception:
            log.warning("planning %s failed", key, exc_info=True)
        finally:
            self.running.discard(key)
        if not ok:
            self.retry_at[key] = monotonic.monotonic() + RETRY_SEC

    async def plan_day(self, day, tz):
        data = self._store()
        term = await self._term(day)
        weekly = await self._weekly(day, term)
        week = await self._week(day, term, weekly)
        trip = self.trip_on(day)
        prev = data["days"].get((day - timedelta(days=1)).isoformat())
        wake = clock_time(prev["up_next"]) if prev else None
        weather = await self._forecast(day)
        raw = await self.app.helper.ask_json(
            self._day_system(), self._day_prompt(day, term, weekly, week, trip, prev, wake, weather), DAY_SCHEMA, 900
        )
        built = build_day(
            day, tz, raw, wake=wake, trip=trip is not None, morning=prev is None, played=tuple(self.cfg.ROUTINE_GAMES)
        )
        if built is None:
            log.info("her model's plan for %s wasn't usable, keeping the simple one", day)
            return False
        data["days"][day.isoformat()] = built
        self._save(day)
        if built["dropped"]:
            log.info("left out of her plan for %s: %s", day, "; ".join(built["dropped"]))
        log.info("planned %s: %s", day, built["summary"] or f"{len(built['spells'])} spells")
        await self._post(f"**planned her {day:%A}**: {built['summary'] or 'done'}")
        self.on_change(day)
        return True

    def _her(self):
        me = getattr(self.app, "user", None)
        return short_name(me) if me is not None else str((self.cfg.NAME_TRIGGERS or ["her"])[0])

    def _life(self):
        return squash(self.cfg.ROUTINE_LIFE) or wording("life.ordinary_person")

    async def _post(self, text):
        relay = getattr(self.app, "relay", None)
        if relay is not None:
            await relay.post(text)

    async def _search(self, query):
        search = getattr(self.app, "search", None)
        if not self.place or search is None or not search.provider:
            return ""
        found = await search.search(query)
        return f"\n{query}:\n{found}" if found else ""

    async def _forecast(self, day):
        tools = getattr(self.app, "tools", None)
        if not (self.cfg.WEATHER and self.place) or tools is None:
            return ""
        try:
            return await tools.day_forecast(self.place, day)
        except Exception:
            log.info("no forecast for %s", day, exc_info=True)
            return ""

    async def _term(self, day):
        data = self._store()
        term = data["term"]
        checked, until = iso_date(term.get("checked")), iso_date(term.get("until"))
        if checked and until and (day - checked).days < TERM_RECHECK_DAYS and until >= day:
            return term
        year = day.year if day.month >= 8 else day.year - 1
        found = await self._search(say("life.search_calendar", place=self.place, year=year, next_year=year + 1))
        found += await self._search(say("life.search_holidays", place=self.place, year=day.year))
        raw = await self.app.helper.ask_json(
            wording("life.year_system"),
            (
                say(
                    "life.year_who", who=self._life(), place=self.place or "not given", today=format(day, "%A %Y-%m-%d")
                )
                + "\n"
            )
            + (
                ("\n" + say("life.search_results", found=found) + "\n\n")
                if found
                else ("\n" + wording("life.no_search_results") + "\n")
            )
            + wording("life.year_fields"),
            TERM_SCHEMA,
            500,
        )
        if raw is None:
            return term
        phase = raw.get("phase") if raw.get("phase") in PHASES else "term"
        ends = iso_date(raw.get("until"))
        ends = min(ends if ends and ends >= day else day + timedelta(days=7), day + timedelta(days=120))
        holidays = []
        for h in raw.get("holidays") or []:
            when = iso_date(h.get("date")) if isinstance(h, dict) else None
            if when and day <= when <= day + timedelta(days=90):
                holidays.append({"date": when.isoformat(), "name": cut(squash(h.get("name")), 60)})
        note = squash(raw.get("note"))[:200]
        term = {
            "checked": day.isoformat(),
            "phase": phase,
            "until": ends.isoformat(),
            "semester": squash(raw.get("semester"))[:20] or f"{year}",
            "holidays": holidays[:10],
            "note": note if allowed(note) else "",
        }
        data["term"] = term
        self._save(day)
        log.info("her year: %s until %s (%s)", phase, term["until"], term["semester"])
        return term

    async def _weekly(self, day, term):
        data = self._store()
        key = term.get("semester") or str(day.year)
        if data["weekly"].get("key") == key:
            return data["weekly"]["items"]
        raw = await self.app.helper.ask_json(
            wording("life.weekly_system"),
            say(
                "life.weekly",
                who=self._life(),
                place=self.place or "not given",
                phase=term.get("phase", "term"),
                until=term.get("until", "?"),
                note=term.get("note", ""),
            ),
            WEEKLY_SCHEMA,
            900,
        )
        if raw is None:
            return data["weekly"].get("items") or []
        items = check_weekly(raw)
        data["weekly"] = {"key": key, "items": items}
        self._save(day)
        log.info("her weekly schedule for %s: %d things", key, len(items))
        return items

    async def _week(self, day, term, weekly):
        data = self._store()
        monday = day - timedelta(days=day.weekday())
        if monday.isoformat() in data["weeks"]:
            return data["weeks"][monday.isoformat()]
        ended = [iso_date(t["end"]) for t in data["trips"] if iso_date(t["end"]) and t["end"] < monday.isoformat()]
        dates = trip_dates(
            monday,
            self.cfg.OWNER_ID,
            float(self.cfg.ROUTINE_TRIP_CHANCE),
            int(self.cfg.ROUTINE_TRIP_GAP_WEEKS),
            self.cfg.ROUTINE_TRIP_DAYS,
            max(ended) if ended else None,
            term.get("phase"),
        )
        sunday = monday + timedelta(days=6)
        found = await self._search(say("life.search_events", place=self.place, week=format(monday, "%d %B %Y")))
        last = [
            f"{k}: {v['summary']}" for k, v in sorted(data["days"].items())[-7:] if v.get("summary") and k < str(monday)
        ]
        timetable = "; ".join(f"{i['day']} {i['from']}-{i['to']} {i['what']}" for i in weekly) or "nothing fixed"
        trip_ask = (
            say("life.trip", start=format(dates[0], "%A %d %B"), end=format(dates[1], "%A %d %B"))
            if dates
            else wording("life.no_trip")
        )
        raw = await self.app.helper.ask_json(
            say("life.week_system", her=self._her()),
            (
                say(
                    "life.week",
                    who=self._life(),
                    place=self.place or "not given",
                    monday=format(monday, "%A %d %B"),
                    sunday=format(sunday, "%A %d %B %Y"),
                    phase=term.get("phase", "term"),
                    until=term.get("until", "?"),
                    note=term.get("note", ""),
                    holidays=", ".join(h["date"] + " " + h["name"] for h in term.get("holidays", [])) or "none",
                    timetable=timetable,
                )
                + "\n"
            )
            + ((wording("life.week_last_days") + "\n") + "\n".join(last) + "\n" if last else "")
            + (("\n" + say("life.week_around", found=found) + "\n") if found else "")
            + ("\n" + say("life.week_plans", limits=LIMITS, trip=trip_ask)),
            WEEK_SCHEMA,
            500,
        )
        if raw is None:
            return {"plans": []}
        plans = []
        for p in raw.get("plans") or []:
            when = iso_date(p.get("date")) if isinstance(p, dict) else None
            what = tidy_what(p.get("what")) if when else ""
            if when and monday <= when <= sunday and allowed(what, self._away(dates, when)):
                plans.append({"date": when.isoformat(), "what": what})
        week = {"plans": plans[:5]}
        where, why = squash(raw.get("trip_where"))[:60], squash(raw.get("trip_why"))[:80]
        if dates and where and allowed(f"{where} {why}", trip=True):
            trip = {"start": dates[0].isoformat(), "end": dates[1].isoformat(), "where": where, "why": why}
            data["trips"].append(trip)
            log.info("she's going to %s, %s to %s (%s)", where, trip["start"], trip["end"], why)
            await self._post(f"**trip planned**: {where} ({why}), {trip['start']} to {trip['end']}")
        data["weeks"][monday.isoformat()] = week
        self._save(day)
        return week

    @staticmethod
    def _away(dates, day):
        return bool(dates) and dates[0] <= day <= dates[1]

    def _day_system(self):
        return (
            say("life.day_system", her=self._her(), who=self._life())
            + ((" " + say("life.day_lives_in", place=self.place)) if self.place else "")
            + (" " + say("life.day_rules", limits=LIMITS))
        )

    def _day_prompt(self, day, term, weekly, week, trip, prev, wake, weather):
        dow = WEEKDAYS[day.weekday()]
        holiday = [h["name"] for h in term.get("holidays", []) if h["date"] == day.isoformat()]
        lines = [say("life.day_date", day=format(day, "%A %d %B %Y"))]
        phase = term.get("phase", "term")
        lines.append(say("life.day_part", phase=phase, until=term.get("until", "?"), note=term.get("note", "")).strip())
        fixed = [f"{i['from']}-{i['to']} {i['what']}" for i in weekly if i["day"] == dow]
        if holiday:
            lines.append(say("life.day_holiday", holiday=", ".join(holiday)))
        elif trip:
            n = (day - date.fromisoformat(trip["start"])).days + 1
            total = (date.fromisoformat(trip["end"]) - date.fromisoformat(trip["start"])).days + 1
            lines.append(say("life.day_away", where=trip["where"], why=trip["why"], n=n, total=total))
        elif fixed and phase == "term":
            lines.append((wording("life.day_fixed") + " ") + "; ".join(fixed))
        elif phase == "exams":
            lines.append(wording("life.day_exams"))
        plans = [p["what"] for p in week.get("plans", []) if p["date"] == day.isoformat()]
        if plans:
            lines.append((wording("life.day_planned") + " ") + "; ".join(plans))
        if prev and prev.get("summary"):
            lines.append(say("life.day_yesterday", summary=prev["summary"]))
        if wake:
            lines.append(say("life.day_wake", wake=format(wake, "%H:%M")))
        sleep = self.cfg.ROUTINE_SLEEP or []
        if len(sleep) == 2:
            lines.append(say("life.day_sleep", bedtime=sleep[0], wake=sleep[1]))
        if self.cfg.ROUTINE_GAMES:
            lines.append((wording("life.day_games") + " ") + ", ".join(map(str, self.cfg.ROUTINE_GAMES)))
            recent = [s[4] for s in (prev or {}).get("spells", []) if len(s) > 4 and s[4]]
            if recent:
                lines.append((wording("life.day_played") + " ") + ", ".join(dict.fromkeys(recent)))
        if weather:
            lines.append(say("life.day_weather", weather=weather))
        facts = self._own_facts()
        if facts:
            lines.append((wording("life.day_her_facts") + " ") + "; ".join(facts))
        return "\n".join(lines)

    def _own_facts(self):
        if not (self.cfg.MEMORY and self.cfg.SELF_NOTES):
            return []
        own = getattr(getattr(self.app, "memory", None), "own", None) or {}
        facts = sorted(own.get("facts") or [], key=lambda f: -int(f.get("id", 0)))[:12]
        return [cut(squash(f.get("text")), 120) for f in facts if f.get("text")]
