import asyncio
from types import SimpleNamespace as NS

from mitski.chat import sender as sender_module


def watch_model(world):
    """Records whether "is typing" was showing every time her model (reply, retry or helper) was asked something."""
    seen = []
    generate, ask_json = world.app.llm.generate, world.app.helper.ask_json

    async def watched_generate(*args, **kwargs):
        seen.append(getattr(world.channel, "typing_now", 0))
        return await generate(*args, **kwargs)

    async def watched_ask_json(*args, **kwargs):
        seen.append(getattr(world.channel, "typing_now", 0))
        return await ask_json(*args, **kwargs)

    world.app.llm.generate, world.app.helper.ask_json = watched_generate, watched_ask_json
    return seen


async def test_no_typing_while_her_model_is_still_working(world):
    seen = watch_model(world)
    world.app.cfg.THINKING = True
    world.replies.extend(["hope this helps!", "nah im good"])
    await world.send(world.people["anna"], "mitski u ok?")
    assert seen and all(n == 0 for n in seen)
    assert world.channel.typed >= 1 and world.sent_text() == ["nah im good"]
    assert getattr(world.channel, "typing_now", 0) == 0


def record_sleeps(monkeypatch, channel, world):
    world.app.cfg.TYPING_CPS = 9
    slept = []
    real = asyncio.sleep

    async def sleep(seconds=0, result=None):
        slept.append((seconds, getattr(channel, "typing_now", 0)))
        return await real(0, result)

    monkeypatch.setattr(sender_module.asyncio, "sleep", sleep)
    return slept


async def test_after_a_slow_draft_she_still_shows_typing_for_a_moment(world, monkeypatch):
    slept = record_sleeps(monkeypatch, world.channel, world)
    out = NS(sent=[], channel=world.channel)
    await world.app.sender._type(out, "ok so basically what happened was this", already_typed=60)
    typed = [s for s, showing in slept if showing]
    assert len(typed) == 1 and typed[0] >= sender_module.SHOWN_TYPING_MIN


async def test_without_a_slow_draft_she_types_it_out_in_full(world, monkeypatch):
    slept = record_sleeps(monkeypatch, world.channel, world)
    line = "ok so basically what happened was this"
    await world.app.sender._type(NS(sent=[], channel=world.channel), line, already_typed=0)
    [typed] = [s for s, showing in slept if showing]
    assert typed >= len(line) / (world.app.cfg.TYPING_CPS * 1.2)
