import asyncio
import logging
import time
from collections import deque

import pytest

from mitski.core.clock import ago, per_tick
from mitski.core.collections import BoundedDict, BoundedSet, drop_where, window_count
from mitski.core.metrics import Metrics
from mitski.core.storage import JsonFile
from mitski.core.tasks import Background
from mitski.core.text import cut, snowflakes, squash


def test_bounded_dict_evicts_the_oldest_and_refreshes_on_write():
    d = BoundedDict(2)
    d["a"], d["b"] = 1, 2
    d["a"] = 3
    d["c"] = 4
    assert list(d) == ["a", "c"]


def test_bounded_set():
    s = BoundedSet(2)
    for x in "abc":
        s.add(x)
    assert "a" not in s and "c" in s and len(s) == 2


def test_drop_where_and_window_count():
    d = {1: 1, 2: 2, 3: 3}
    assert drop_where(d, lambda k, v: v > 1) == 2
    assert d == {1: 1}
    times = deque([0, 50, 100])
    assert window_count(times, 60, now=120) == 1
    assert list(times) == [100]


@pytest.mark.parametrize(
    ("text", "limit", "out"),
    [("hello", 10, "hello"), ("hello world", 6, "hello…"), (None, 3, "")],
)
def test_cut(text, limit, out):
    assert cut(text, limit) == out


def test_snowflakes_and_squash():
    assert snowflakes("<@123456789012345678> 123 123456789012345678 987654321098765432") == [
        123456789012345678,
        987654321098765432,
    ]
    assert squash("  a \n\t b ") == "a b"


@pytest.mark.parametrize(
    ("p_hour", "seconds", "low", "high"),
    [(0.5, 3600, 0.499, 0.501), (0.0, 3600, 0, 0), (1.0, 3600, 0.95, 0.95), (0.5, 60, 0.01, 0.012)],
)
def test_per_tick(p_hour, seconds, low, high):
    assert low <= per_tick(p_hour, seconds) <= high


@pytest.mark.parametrize(
    ("seconds", "phrase"),
    [(60, "just now"), (1800, "earlier"), (7200, "today"), (90_000, "yesterday"), (5 * 86400, "5 days ago")],
)
def test_ago(seconds, phrase):
    assert ago(0, seconds) == phrase


def test_json_file_survives_corruption(tmp_path):
    f = JsonFile(tmp_path / "x.json", {"n": 0})
    assert f.load() == {"n": 0}
    f.save({"n": 2})
    assert f.load() == {"n": 2}
    (tmp_path / "x.json").write_text("{broken", encoding="utf-8")
    assert f.load() == {"n": 0}


def test_metrics_percentiles():
    m = Metrics()
    for i in range(10):
        with m.trace("direct") as t:
            Metrics.llm_call("reply", 0.1)
            t.first_send = t.started + i
    report = m.report()
    assert "10 replies" in report
    assert "p50 4.5s" in report
    assert "p50 1" in report


def test_metrics_ignore_calls_outside_a_trace():
    Metrics.llm_call("reply", 1.0)
    assert Metrics.current() is None


async def test_background_keeps_references_and_logs_failures(caplog):
    tasks = Background()

    async def boom():
        raise RuntimeError("nope")

    gate = asyncio.Event()
    waiter = tasks.spawn(gate.wait(), name="waiter")
    with caplog.at_level(logging.ERROR, logger="mitski.tasks"):
        failing = tasks.spawn(boom(), name="boom")
        await asyncio.gather(failing, return_exceptions=True)
        await asyncio.sleep(0)
    assert "boom failed" in caplog.text
    assert len(tasks) == 1
    gate.set()
    await waiter
    await asyncio.sleep(0)
    assert len(tasks) == 0


async def test_background_tasks_do_not_inherit_a_trace():
    m, tasks = Metrics(), Background()
    seen = []

    async def child():
        seen.append(Metrics.current())

    with m.trace("direct"):
        await tasks.spawn(child())
    assert seen == [None]


def test_monotonic_is_used_for_traces():
    with Metrics().trace("dm") as t:
        pass
    assert t.started <= time.monotonic()
