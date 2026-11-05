import time
from collections import defaultdict
from dataclasses import dataclass

from mitski.core.collections import BoundedDict, BoundedSet, deque_dict, drop_where

HOUR = 3600
TYPING_SEEN = 60


@dataclass
class Engagement:
    until: float
    budget: int = 0

    def live(self, now=None):
        return (time.monotonic() if now is None else now) < self.until


class ChatState:
    def __init__(self, cfg):
        self.cfg = cfg
        self.waiting = {}
        self.engaged = {}
        self.channel_locks = {}
        self.addressed = BoundedDict(5000)
        self.chime_rolls = BoundedDict(2000)
        self.requeued = BoundedSet(2000)
        self.last_history = BoundedDict(64)
        self.last_msg_time = {}
        self.last_typing = {}
        self.msg_count = defaultdict(int)
        self.threshold_base = {}
        self.last_active = {}
        self.ambient_times = deque_dict()
        self.activity = deque_dict(500)
        self.chan_log = deque_dict(300)
        self.recent_said = deque_dict(15)
        self.react_times = deque_dict()
        self.known_names = defaultdict(set)
        self.her_spoke = {}
        self.exchanges = deque_dict()
        self.dm_opened = {}
        self.dm_rolled = {}
        self.dm_promised = {}
        self.dm_unanswered = BoundedSet(2000)
        self.command_replies = BoundedSet(2000)

    def channel_busy(self, channel_id):
        lock = self.channel_locks.get(channel_id)
        return bool(lock and lock.locked()) or any(k[0] == channel_id for k in self.waiting)

    def forget_channel(self, channel_id):
        for store in (self.waiting, self.engaged, self.last_msg_time, self.last_typing):
            drop_where(store, lambda k, _v: k[0] == channel_id)
        for store in (self.msg_count, self.threshold_base, self.last_active, self.ambient_times, self.recent_said):
            store.pop(channel_id, None)

    def forget_guild(self, channel_ids):
        for cid in channel_ids:
            self.forget_channel(cid)

    def forget_user(self, user_id):
        for store in (self.waiting, self.engaged, self.last_msg_time, self.last_typing):
            drop_where(store, lambda k, _v: k[1] == user_id)
        for store in (self.exchanges, self.dm_opened, self.dm_rolled, self.dm_promised):
            store.pop(user_id, None)
        self.dm_unanswered.discard(user_id)

    def sweep(self, now=None):
        now = time.monotonic() if now is None else now
        cfg = self.cfg
        dm_keep = max(cfg.dm_cooldown, cfg.dm_window, cfg.dm_promise_cooldown, 600)
        removed = drop_where(self.engaged, lambda _k, e: not e.live(now))
        removed += drop_where(self.last_msg_time, lambda _k, t: now - t > HOUR)
        removed += drop_where(self.last_typing, lambda _k, t: now - t > TYPING_SEEN)
        removed += drop_where(self.channel_locks, lambda cid, lock: not lock.locked() and not self.channel_busy(cid))
        removed += drop_where(self.exchanges, lambda _k, times: not times or now - times[-1] > cfg.dm_window)
        removed += drop_where(self.react_times, lambda _k, times: not times or now - times[-1] > HOUR)
        removed += drop_where(self.ambient_times, lambda _k, times: not times or now - times[-1] > HOUR)
        for store in (self.dm_opened, self.dm_rolled, self.dm_promised):
            removed += drop_where(store, lambda _k, t: now - t > dm_keep)
        return removed

    def stats(self):
        sizes = {
            "waiting": len(self.waiting),
            "engaged": len(self.engaged),
            "locks": len(self.channel_locks),
            "addressed": len(self.addressed),
            "typing": len(self.last_typing),
            "dm timers": len(self.dm_opened) + len(self.dm_rolled) + len(self.dm_promised),
        }
        return "state: " + " · ".join(f"{k} {v}" for k, v in sizes.items())
