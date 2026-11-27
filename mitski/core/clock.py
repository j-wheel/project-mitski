from datetime import datetime

from mitski.core import logs
from mitski.core.texts import fill, say, wording

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
    words = wording("chat.time_of_day")
    part = (
        words["night"]
        if h < 5
        else words["early_morning"]
        if h < 8
        else words["morning"]
        if h < 11
        else words["midday"]
        if h < 14
        else words["afternoon"]
        if h < 18
        else words["evening"]
        if h < 22
        else words["late_night"]
    )
    return say("chat.time_now", day=now.strftime("%A"), part=part, time=now.strftime("%H:%M"))


def per_tick(p_hour, seconds):
    p_hour = min(max(p_hour, 0.0), 0.95)
    return 1 - (1 - p_hour) ** (seconds / 3600)


def ago(t, now):
    words = wording("chat.ago")
    s = now - t
    if s < 3600:
        return words["just_now"] if s < 600 else words["earlier"]
    if s < DAY:
        return words["today"]
    n = int(s // DAY)
    if n == 1:
        return words["yesterday"]
    if n < 14:
        return fill(words["days"], n=n)
    if n < 60:
        return fill(words["weeks"], n=n // 7)
    return fill(words["months"], n=n // 30)
