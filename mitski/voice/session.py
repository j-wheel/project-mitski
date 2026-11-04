import time
from dataclasses import dataclass, field


@dataclass
class Session:
    guild: int
    stay_until: float
    why: str
    solo: bool
    owner: int | None
    owner_seen: bool
    peak: int
    joined: float = field(default_factory=time.time)
    had_company: bool = False
    alone_since: float | None = None
    alone_wait: float | None = None
    owner_left: float | None = None
    leave_at: float | None = None
    extended: int = 0

    @property
    def minutes(self):
        return (time.time() - self.joined) / 60

    def moved(self, company):
        self.alone_since = self.alone_wait = None
        self.solo = not company
        self.had_company = bool(company)
