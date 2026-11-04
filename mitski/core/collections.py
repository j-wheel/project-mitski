import time
from collections import OrderedDict, defaultdict, deque


class BoundedDict(OrderedDict):
    def __init__(self, maxlen, *args, **kwargs):
        self.maxlen = maxlen
        super().__init__(*args, **kwargs)

    def __setitem__(self, key, value):
        if key in self:
            self.move_to_end(key)
        super().__setitem__(key, value)
        while len(self) > self.maxlen:
            self.popitem(last=False)


class BoundedSet:
    def __init__(self, maxlen):
        self._items = BoundedDict(maxlen)

    def add(self, item):
        self._items[item] = None

    def discard(self, item):
        self._items.pop(item, None)

    def __contains__(self, item):
        return item in self._items

    def __len__(self):
        return len(self._items)

    def __iter__(self):
        return iter(self._items)


class DefaultBoundedDict(BoundedDict):
    def __init__(self, maxlen, factory):
        super().__init__(maxlen)
        self.factory = factory

    def __missing__(self, key):
        value = self.factory()
        self[key] = value
        return value


def drop_where(mapping, stale):
    gone = [k for k, v in list(mapping.items()) if stale(k, v)]
    for k in gone:
        mapping.pop(k, None)
    return len(gone)


def window_count(times, seconds, now=None):
    now = time.monotonic() if now is None else now
    while times and now - times[0] > seconds:
        times.popleft()
    return len(times)


def deque_dict(maxlen=None):
    return defaultdict(lambda: deque(maxlen=maxlen))
