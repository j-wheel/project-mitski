import asyncio
import contextvars
import heapq
import itertools
import time

REPLY, HELPER, BACKGROUND = 0, 1, 2
PRIORITY = contextvars.ContextVar("gpu_priority", default=HELPER)


def background():
    PRIORITY.set(BACKGROUND)


class GpuLock:
    def __init__(self, quiet=20.0, max_wait=180.0):
        self.quiet = quiet
        self.max_wait = max_wait
        self.last_busy = 0.0
        self._busy = False
        self._holder = HELPER
        self._queue = []
        self._order = itertools.count()

    def locked(self):
        return self._busy

    def waiting(self, above=BACKGROUND):
        return sum(1 for p, _, fut in self._queue if p < above and not fut.done())

    async def acquire(self, priority=None):
        p = min(max(int(PRIORITY.get() if priority is None else priority), REPLY), BACKGROUND)
        if p == BACKGROUND:
            await self._wait_for_quiet()
        if not self._busy and not self.waiting(BACKGROUND + 1):
            self._busy = True
        else:
            await self._queue_up(p)
        if p < BACKGROUND:
            self.last_busy = time.monotonic()
        self._holder = p
        return p

    async def _wait_for_quiet(self):
        start = time.monotonic()
        while True:
            now = time.monotonic()
            left = min(self.quiet - (now - self.last_busy), self.max_wait - (now - start))
            if left <= 0:
                return
            await asyncio.sleep(left)

    async def _queue_up(self, p):
        fut = asyncio.get_running_loop().create_future()
        heapq.heappush(self._queue, (p, next(self._order), fut))
        try:
            await fut
        except asyncio.CancelledError:
            if fut.done() and not fut.cancelled():
                self.release(p)
            raise

    def release(self, p=HELPER):
        if p < BACKGROUND:
            self.last_busy = time.monotonic()
        while self._queue:
            _, _, fut = heapq.heappop(self._queue)
            if not fut.done():
                fut.set_result(None)
                return
        self._busy = False

    def at(self, priority):
        return _Held(self, priority)

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *exc):
        self.release(self._holder)


class _Held:
    def __init__(self, lock, priority):
        self.lock, self.priority, self.p = lock, priority, HELPER

    async def __aenter__(self):
        self.p = await self.lock.acquire(self.priority)
        return self

    async def __aexit__(self, *exc):
        self.lock.release(self.p)
