import datetime as dt
import re
import time

from mitski.core.clock import DAY
from mitski.memory.schema import MONTHS


def parse_date(text):
    try:
        y, m, d = (int(x) for x in str(text).split("-"))
        return dt.date(y, m, d)
    except (ValueError, TypeError):
        return None


def plan_date(text):
    date = parse_date(text) if text else None
    if date and -30 <= (date - dt.date.today()).days <= 730:
        return date.isoformat()
    return None


def parse_birthday(text):
    t = text.lower()
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        y, mo, d = map(int, m.groups())
        return _valid_bday(mo, d, y)
    for i, name in enumerate(MONTHS, 1):
        if re.search(r"\b" + name[:3] + r"[a-z]*\b", t):
            dm = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", t)
            ym = re.search(r"\b(19\d{2}|20\d{2})\b", t)
            if dm:
                return _valid_bday(i, int(dm.group(1)), int(ym.group(1)) if ym else None)
            return None
    return None


def _valid_bday(mo, d, y):
    try:
        dt.date(y or 2000, mo, d)
    except ValueError:
        return None
    if y and not (1920 <= y <= dt.date.today().year - 5):
        y = None
    return mo, d, y


def birthday_in(year, md):
    try:
        return dt.date(year, md[0], md[1])
    except ValueError:
        return dt.date(year, 3, 1)


def birthdays_between(md, t0, t1):
    d0, d1 = dt.date.fromtimestamp(t0), dt.date.fromtimestamp(t1)
    return sum(1 for y in range(d0.year, d1.year + 1) if d0 < birthday_in(y, md) <= d1)


def said_ago(t, now=None):
    secs = (now or time.time()) - t
    if secs < 3600:
        return "a little while ago"
    if secs < 6 * 3600:
        return "a few hours ago"
    days = int(secs // DAY)
    if days == 0:
        return "earlier today"
    if days == 1:
        return "yesterday"
    if days < 14:
        return f"{days} days ago"
    if days < 60:
        return f"{days // 7} weeks ago"
    return f"{days // 30} months ago"


def until(date, today):
    n = (date - today).days
    if n == 0:
        return "today"
    if n == 1:
        return "tomorrow"
    if n < 0:
        return "yesterday" if n == -1 else f"{-n} days ago"
    return f"{date.strftime('%A')}, in {n} days" if n < 7 else f"{date.strftime('%B')} {date.day}, in {n} days"
