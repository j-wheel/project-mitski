from mitski.llm.client import ModelUnavailable
from mitski.testing.fakes import FakeChannel


async def test_a_mention_gets_one_reply(world):
    world.replies.append("heyy whats up")
    await world.send(world.people["anna"], "mitski hiii")
    assert world.sent_text() == ["heyy whats up"]


async def test_reply_is_recorded_in_metrics(world):
    world.replies.append("yeah")
    await world.send(world.people["anna"], "mitski u there")
    trace = world.app.metrics.done[-1]
    assert trace.outcome == "sent"
    assert trace.to_first_send is not None
    assert "compose" in trace.stages


async def test_ignored_users_get_nothing(world):
    anna = world.people["anna"]
    world.app.cfg.ignored.add(anna.id)
    await world.send(anna, "mitski hello??")
    assert world.sent_text() == []
    assert world.prompts == []


async def test_quiet_server_stays_silent_for_everyone_but_the_owner(world):
    world.app.away.quiet(world.guild.id, 30)
    await world.send(world.people["bob"], "mitski hey")
    assert world.sent_text() == []
    world.replies.append("ok fine")
    await world.send(world.owner, "mitski you can talk again")
    assert not world.app.away.is_quiet(world.guild.id)
    assert world.sent_text() == ["ok fine"]


async def test_messages_outside_her_channels_are_ignored(world):
    other = FakeChannel(world.client, world.guild, "off-topic")
    msg = world.say(world.people["anna"], "mitski hi")
    msg.channel = other
    await world.app.router.route(msg)
    assert world.sent_text() == []


async def test_empty_drafts_are_not_sent(world):
    world.replies.append("")
    await world.send(world.people["anna"], "mitski hi")
    assert world.sent_text() == []
    assert world.app.metrics.done[-1].outcome != "sent"


async def test_model_outage_drops_the_reply_quietly(world):
    async def down(*args, **kwargs):
        raise ModelUnavailable("down")

    world.app.llm.generate = down
    await world.send(world.people["anna"], "mitski hi")
    assert world.sent_text() == []
    assert world.app.metrics.done[-1].outcome == "model unavailable"


async def test_retries_are_counted(world):
    world.replies.extend(["as an ai i cant", "nah"])
    await world.send(world.people["anna"], "mitski u ok")
    assert world.app.metrics.done[-1].events["redo robotic"] == 1
