import time

from mitski.chat import pipeline
from mitski.chat.pipeline import Reply
from mitski.testing.fakes import FakeMessage


async def test_typing_before_their_message_doesnt_hold_her_up(world):
    key = (world.channel.id, world.people["anna"].id)
    now = time.monotonic()
    world.app.state.last_typing[key] = now - 1
    world.app.state.last_msg_time[key] = now - 0.5
    start = time.monotonic()
    await world.app.pipeline.wait_quiet(key, max_wait=2, debounce=0)
    assert time.monotonic() - start < 0.5


async def test_typing_after_their_message_still_waits(world):
    key = (world.channel.id, world.people["anna"].id)
    now = time.monotonic()
    world.app.state.last_msg_time[key] = now - 3
    world.app.state.last_typing[key] = now - 0.5
    start = time.monotonic()
    await world.app.pipeline.wait_quiet(key, max_wait=0.6, debounce=0)
    assert time.monotonic() - start >= 0.5


def reply_to(world, person, waited=0.0):
    msg = FakeMessage(world.channel, person, "mitski what u doing")
    return Reply(world.channel, "direct", trigger=msg, waited=waited)


async def test_in_a_live_chat_she_is_often_quick(world):
    anna = world.people["anna"]
    world.app.cfg.QUICK_REPLY_CHANCE = 1.0
    world.app.addressing.engage(world.channel.id, anna.id)
    pace = world.app.pipeline._pace(reply_to(world, anna))
    assert pipeline.QUICK_PACE[0] <= pace <= pipeline.QUICK_PACE[1]


async def test_quick_replies_can_be_turned_off_and_never_after_being_busy(world):
    anna = world.people["anna"]
    world.app.addressing.engage(world.channel.id, anna.id)
    world.app.cfg.QUICK_REPLY_CHANCE = 1.0
    assert world.app.pipeline._pace(reply_to(world, anna, waited=300)) == 1.0
    world.app.cfg.QUICK_REPLY_CHANCE = 0
    assert world.app.pipeline._pace(reply_to(world, anna)) == 1.0


async def test_out_of_the_blue_she_is_quick_less_often(world, monkeypatch):
    anna = world.people["anna"]
    world.app.cfg.QUICK_REPLY_CHANCE = 0.5
    monkeypatch.setattr(pipeline.random, "random", lambda: 0.3)
    world.app.addressing.engage(world.channel.id, anna.id)
    assert world.app.pipeline._pace(reply_to(world, anna)) < 1
    world.app.state.engaged.clear()
    assert world.app.pipeline._pace(reply_to(world, anna)) == 1.0


async def test_her_plan_is_worked_out_once_even_when_started_early(world):
    planned = []

    async def ask_json(system, user, schema, max_tokens=400, think=False):
        if "reply_type" not in (schema or {}).get("properties", {}):
            return None
        planned.append(user)
        return {"to_her": "her", "wants": "", "reply_type": "small_talk", "answer": "", "tools": []}

    world.app.cfg.THINKING = True
    world.app.helper.ask_json = ask_json
    world.replies.append("just chilling, u?")
    await world.send(world.people["anna"], "mitski what are u up to today")
    assert world.sent_text() == ["just chilling, u?"]
    assert len(planned) == 1


async def test_the_chat_is_fetched_once_while_nothing_new_comes_in(world, monkeypatch):
    channel = world.channel
    msg = FakeMessage(channel, world.people["anna"], "mitski hey")
    channel.last_message_id = msg.id
    fetches = []
    real = type(channel).history

    def counted(self, *args, **kwargs):
        fetches.append(1)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(type(channel), "history", counted)
    context = world.app.context
    await context.build(channel, "direct", msg)
    await context.build(channel, "direct", msg)
    assert len(fetches) == 1
    newer = FakeMessage(channel, world.people["bob"], "yo")
    channel.last_message_id = newer.id
    await context.build(channel, "direct", msg)
    assert len(fetches) == 2


async def test_a_profile_lookup_is_done_when_the_profile_is_in(world):
    ages = world.app.ages
    anna = world.people["anna"]

    class Profile:
        bio = "hi"
        metadata = None
        connections = ()

    async def profile():
        return Profile()

    anna.profile = profile
    world.app.cfg.PROFILE_READ = True
    await ages.check_profile(anna)
    assert ages.next_fetch > time.monotonic()
