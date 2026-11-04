from datetime import datetime

from mitski.core import logs

log = logs.get("clock")

DAY = 86400


class Clock:
    def __init__(self, timezone=""):
        self.zone = None
        if timezone:
            try:
                from zoneinfo import ZoneInfo

                self.zone = ZoneInfo(timezone)
            except Exception:
                log.warning(
                    "unknown TIMEZONE %r (on windows: pip install tzdata), using this computer's clock", timezone
                )

    def now(self):
        return datetime.now(self.zone) if self.zone else datetime.now().astimezone()

    @property
    def hour(self):
        return self.now().hour

    @property
    def late(self):
        return 1 <= self.now().hour < 7


def time_phrase(now):
    h = now.hour
    part = (
        "in the middle of the night"
        if h < 5
        else "early in the morning"
        if h < 8
        else "in the morning"
        if h < 11
        else "around midday"
        if h < 14
        else "in the afternoon"
        if h < 18
        else "in the evening"
        if h < 22
        else "late at night"
    )
    return f"It's {now.strftime('%A')} {part} ({now.strftime('%H:%M')})."


def per_tick(p_hour, seconds):
    p_hour = min(max(p_hour, 0.0), 0.95)
    return 1 - (1 - p_hour) ** (seconds / 3600)


def ago(t, now):
    s = now - t
    if s < 3600:
        return "just now" if s < 600 else "earlier"
    if s < DAY:
        return "today"
    n = int(s // DAY)
    if n == 1:
        return "yesterday"
    if n < 14:
        return f"{n} days ago"
    if n < 60:
        return f"{n // 7} weeks ago"
    return f"{n // 30} months ago"
