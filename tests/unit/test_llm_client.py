import asyncio
import time

import pytest

from mitski.core.metrics import Metrics
from mitski.llm.client import Breaker, LlamaClient, ModelUnavailable
from mitski.llm.gpu import GpuLock


class App:
    def __init__(self, cfg):
        self.cfg = cfg
        self.gpu = GpuLock(quiet=0)
        self.metrics = Metrics()


def test_breaker_opens_after_repeated_failures():
    b = Breaker(after=2, pause=60)
    assert not b.failed()
    assert b.failed()
    assert b.open
    b.worked()
    assert not b.open and b.failures == 0


def test_breaker_reopens_only_after_the_pause():
    b = Breaker(after=1, pause=0.01)
    assert b.failed()
    time.sleep(0.02)
    assert not b.open


@pytest.fixture
def client(make_cfg):
    return LlamaClient(App(make_cfg(LLM_TIMEOUT_SEC=0.05, LLM_PAUSE_AFTER=2, LLM_PAUSE_SEC=60)))


async def test_a_hung_server_times_out_then_pauses(client):
    async def hang(payload):
        await asyncio.sleep(10)

    client._post = hang
    for _ in range(2):
        with pytest.raises(ModelUnavailable):
            await client.generate("hi")
    assert client.breaker.open
    with pytest.raises(ModelUnavailable, match="failed 2 times"):
        await client.generate("hi")
    assert not client.app.gpu.locked()
    assert client.app.metrics.totals["model failures"] == 2


async def test_success_resets_the_failures(client):
    calls = []

    async def flaky(payload):
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError
        return {"content": "yo"}

    client._post = flaky
    with pytest.raises(ModelUnavailable):
        await client.generate("hi")
    assert await client.generate("hi") == "yo"
    assert client.breaker.failures == 0


def test_fallbacks_show_up_in_the_report():
    m = Metrics()
    with m.trace("direct") as t:
        Metrics.event("redo echo")
        t.first_send = t.started + 1
    assert "fallbacks per 100 replies: redo echo 100" in m.report()
