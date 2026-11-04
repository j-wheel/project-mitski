import asyncio
import contextvars

from mitski.core import logs

log = logs.get("tasks")


class Background:
    def __init__(self):
        self._tasks = set()

    def spawn(self, coro, name=None):
        task = asyncio.get_running_loop().create_task(coro, name=name, context=contextvars.Context())
        self._tasks.add(task)
        task.add_done_callback(self._finished)
        return task

    def later(self, delay, coro, name=None):
        async def run():
            await asyncio.sleep(delay)
            await coro

        return self.spawn(run(), name=name)

    def _finished(self, task):
        self._tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            log.error("background task %s failed", task.get_name(), exc_info=error)

    def __len__(self):
        return len(self._tasks)

    async def cancel_all(self):
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
