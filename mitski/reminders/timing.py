import contextlib
import re
from datetime import datetime, timedelta

WORD_NUMBERS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "half a": 0.5,
    "half an": 0.5,
    "a couple of": 2,
    "a couple": 2,
    "couple": 2,
    "a few": 3,
    "few": 3,
}
UNITS = {
    "s": 1 / 60,
    "sec": 1 / 60,
    "secs": 1 / 60,
    "second": 1 / 60,
    "seconds": 1 / 60,
    "m": 1,
    "min": 1,
    "mins": 1,
    "minute": 1,
    "minutes": 1,
    "h": 60,
    "hr": 60,
    "hrs": 60,
    "hour": 60,
    "hours": 60,
    "d": 1440,
    "day": 1440,
    "days": 1440,
    "w": 10080,
    "week": 10080,
    "weeks": 10080,
}
_WORDS = "|".join(sorted((re.escape(w) for w in WORD_NUMBERS), key=len, reverse=True))
_NUM = rf"(?:(?<![\d.,])\d+(?:[.,]\d+)?(?=\s*[a-z])|(?<![a-z])(?:{_WORDS})(?=\s))"
_UNIT = r"(?:" + "|".join(sorted(UNITS, key=len, reverse=True)) + r")"
_PAIR = rf"{_NUM}\s*{_UNIT}(?![a-z])"
IN_DELAY = re.compile(rf"\bin\s+({_PAIR}(?:\s*(?:,|and|&)?\s*{_PAIR})*)", re.I)
PAIR = re.compile(rf"({_NUM})\s*({_UNIT})(?![a-z])", re.I)
HALF_HOUR = re.compile(r"\bin\s+(?:half an hour|a half hour|30 ?min)\b", re.I)
HINT = re.compile(
    r"\b(?:remind|reminder|don'?t let (?:me|him|her|them|\w+) forget|ping (?:me|him|her|them|\w+) (?:in|at|when|tmrw|tomorrow)|"
    r"tell (?:me|him|her|them|\w+) (?:in|at) \d)",
    re.I,
)


def delay_minutes(text):
    text = str(text or "")
    if HALF_HOUR.search(text):
        return 30.0
    m = IN_DELAY.search(text)
    if not m:
        return None
    total = 0.0
    for num, unit in PAIR.findall(m.group(1)):
        n = WORD_NUMBERS.get(num.lower())
        if n is None:
            n = float(num.replace(",", "."))
        total += n * UNITS[unit.lower()]
    return total or None


def due_time(text, plan, now):
    plan = plan or {}
    mins = delay_minutes(text)
    if mins is None:
        try:
            mins = float(plan.get("in_minutes") or 0) or None
        except (TypeError, ValueError):
            mins = None
    if mins:
        return now + timedelta(minutes=mins)
    clock = str(plan.get("at_time") or "").strip()
    m = re.fullmatch(r"(\d{1,2})[:.](\d{2})", clock)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    day = now.date()
    date = str(plan.get("on_date") or "").strip()
    if date:
        with contextlib.suppress(ValueError):
            day = datetime.strptime(date, "%Y-%m-%d").date()
    when = now.replace(year=day.year, month=day.month, day=day.day, hour=int(m.group(1)), minute=int(m.group(2)))
    when = when.replace(second=0, microsecond=0)
    if when <= now:
        when += timedelta(days=1)
    return when


def describe(when, now):
    mins = (when - now).total_seconds() / 60
    clock = when.strftime("%H:%M")
    if mins < 60:
        rel = f"in {max(1, round(mins))} min"
    elif mins < 48 * 60:
        h = mins / 60
        rel = f"in {h:.0f} hours" if h >= 3 or abs(h - round(h)) < 0.1 else f"in {h:.1f} hours"
    else:
        rel = f"in {round(mins / 1440)} days"
    day = (
        "today"
        if when.date() == now.date()
        else "tomorrow"
        if when.date() == (now + timedelta(days=1)).date()
        else when.strftime("%A %d %b")
    )
    return f"{rel} ({day} at {clock})"
