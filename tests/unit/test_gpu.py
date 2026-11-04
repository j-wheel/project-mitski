import asyncio

from mitski.llm.gpu import BACKGROUND, HELPER, REPLY, GpuLock


async def test_replies_jump_the_queue():
    lock = GpuLock(quiet=0)
    order = []

    async def job(name, priority):
        async with lock.at(priority):
            order.append(name)
            await asyncio.sleep(0)

    await lock.acquire(HELPER)
    waiting = [
        asyncio.create_task(job("helper", HELPER)),
        asyncio.create_task(job("background", BACKGROUND)),
        asyncio.create_task(job("reply", REPLY)),
    ]
    await asyncio.sleep(0.01)
    assert lock.waiting() == 2
    lock.release(HELPER)
    await asyncio.gather(*waiting)
    assert order == ["reply", "helper", "background"]
    assert not lock.locked()


async def test_background_waits_for_a_quiet_gpu():
    lock = GpuLock(quiet=0.05)
    async with lock.at(REPLY):
        pass
    start = asyncio.get_running_loop().time()
    async with lock.at(BACKGROUND):
        waited = asyncio.get_running_loop().time() - start
    assert waited >= 0.04


async def test_a_cancelled_waiter_does_not_hold_the_lock():
    lock = GpuLock(quiet=0)
    await lock.acquire(REPLY)
    waiter = asyncio.create_task(lock.acquire(HELPER))
    await asyncio.sleep(0.01)
    waiter.cancel()
    await asyncio.gather(waiter, return_exceptions=True)
    lock.release(REPLY)
    assert not lock.locked()
    async with lock:
        assert lock.locked()
    assert not lock.locked()
