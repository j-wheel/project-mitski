import time
from dataclasses import asdict, dataclass, field

from mitski.core import logs
from mitski.core.storage import JsonFile

log = logs.get("reminders")


@dataclass
class Reminder:
    id: int
    user: int
    by: int
    channel: int
    guild: int | None
    due: float
    what: str
    made: float = field(default_factory=time.time)
    msg: int | None = None

    @property
    def for_themselves(self):
        return self.user == self.by


class Reminders:
    def __init__(self, cfg):
        self.on = cfg.REMINDERS
        self.max_per_user = cfg.REMINDERS_MAX_PER_USER
        self.max_days = cfg.REMINDERS_MAX_DAYS
        self.file = JsonFile(cfg.paths.data_file("reminders.json"), {"next_id": 1, "items": []})
        self.next_id = 1
        self.items = []

    def load(self):
        saved = self.file.load()
        self.next_id = int(saved.get("next_id") or 1)
        self.items = []
        for raw in saved.get("items") or []:
            try:
                self.items.append(Reminder(**raw))
            except TypeError:
                log.warning("skipped a broken reminder: %r", raw)

    def save(self):
        self.file.save({"next_id": self.next_id, "items": [asdict(r) for r in self.items]})

    def by_source(self, msg_id):
        return next((r for r in self.items if r.msg == msg_id), None)

    def pending_from(self, uid):
        return sum(1 for r in self.items if r.by == uid)

    def add(self, user_id, by_id, channel_id, guild_id, due, what, msg_id=None):
        r = Reminder(
            id=self.next_id,
            user=int(user_id),
            by=int(by_id),
            channel=int(channel_id),
            guild=int(guild_id) if guild_id else None,
            due=float(due),
            what=str(what)[:200],
            msg=msg_id,
        )
        self.next_id += 1
        self.items.append(r)
        self.save()
        return r

    def due_now(self, now=None):
        now = now or time.time()
        return sorted((r for r in self.items if r.due <= now), key=lambda r: r.due)

    def done(self, rid):
        before = len(self.items)
        self.items = [r for r in self.items if r.id != rid]
        if len(self.items) != before:
            self.save()
            return True
        return False

    def cancel(self, ids):
        ids = {int(i) for i in ids}
        gone = [r for r in self.items if r.id in ids]
        if gone:
            self.items = [r for r in self.items if r.id not in ids]
            self.save()
        return gone

    def upcoming(self):
        return sorted(self.items, key=lambda r: r.due)
