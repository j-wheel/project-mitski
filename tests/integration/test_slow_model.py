import asyncio
import contextlib
import logging

import pytest

from mitski.core import logs
from mitski.llm import client as llm_client
from mitski.llm import gpu
from mitski.llm.client import LlamaClient, ModelUnavailable


def real(world, post, timeout=0.05):
    llm = world.app.llm
    world.app.cfg.LLM_TIMEOUT_SEC = timeout
    llm._post = post
    return llm


async def hang(payload):
    await asyncio.Event().wait()


async def background_call(llm):
    gpu.background()
    return await LlamaClient.generate(llm, "notes prompt", helper=True)


async def test_slow_background_work_never_pauses_her_replies(world):
    llm = real(world, hang)
    for _ in range(world.app.cfg.LLM_PAUSE_AFTER + 1):
        with pytest.raises(ModelUnavailable):
            await asyncio.create_task(background_call(llm))
    assert not llm.breaker.open
    assert not world.app.gpu.locked()


async def test_background_work_gets_longer_before_its_given_up_on(world):
    async def a_bit_slow(payload):
        await asyncio.wait_for(asyncio.Event().wait(), 0.08)

    async def answer_after_a_while(payload):
        with contextlib.suppress(TimeoutError):
            await a_bit_slow(payload)
        return {"content": "done"}

    llm = real(world, answer_after_a_while)
    assert await asyncio.create_task(background_call(llm)) == "done"
    with pytest.raises(ModelUnavailable):
        await LlamaClient.generate(llm, "her reply")


async def test_her_own_replies_still_pause_on_a_dead_server(world):
    llm = real(world, hang)
    for _ in range(world.app.cfg.LLM_PAUSE_AFTER):
        with pytest.raises(ModelUnavailable):
            await LlamaClient.generate(llm, "her reply")
    assert llm.breaker.open


class Lines(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


async def test_a_slow_call_says_what_was_slow(world, monkeypatch):
    async def slow_tokens(payload):
        return {
            "content": "ok",
            "timings": {"prompt_n": 9000, "prompt_per_second": 900.0, "predicted_n": 160, "predicted_per_second": 2.1},
        }

    monkeypatch.setattr(llm_client, "SLOW_SEC", 0)
    llm = real(world, slow_tokens)
    log = logs.get("llm")
    seen, level = Lines(), log.level
    log.addHandler(seen)
    log.setLevel(logging.INFO)
    try:
        await LlamaClient.generate(llm, "hi", helper=True)
    finally:
        log.removeHandler(seen)
        log.setLevel(level)
    [line] = [x for x in seen.lines if "call took" in x]
    assert "prompt 9000 tokens at 900/s, wrote 160 at 2.1/s" in line and "out of VRAM" in line
