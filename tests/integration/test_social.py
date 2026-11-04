import time

from mitski.testing.fakes import FakeChannel, FakeMessage, settle


async def test_a_due_reminder_pings_the_person(world):
    anna = world.people["anna"]
    world.replies.append("hey drink some water")
    world.app.reminders.add(anna.id, anna.id, world.channel.id, world.guild.id, time.time() - 1, "drink water")
    await world.app.scheduler.tick()
    assert world.sent_text() == [f"<@{anna.id}> hey drink some water"]
    assert world.app.reminders.items == []


async def test_reminders_wait_while_the_server_is_quiet(world):
    anna = world.people["anna"]
    world.app.away.quiet(world.guild.id, 10)
    world.app.reminders.add(anna.id, anna.id, world.channel.id, world.guild.id, time.time() - 1, "stretch")
    await world.app.scheduler.tick()
    assert world.sent_text() == []
    assert len(world.app.reminders.items) == 1


async def test_owner_wakes_her_up_and_gets_an_answer(world):
    await world.app.sleep.go_away(world.guild, hours=2, bye=False)
    await world.send(world.people["bob"], "mitski wake up")
    assert world.sent_text() == []
    world.replies.append("mm im up")
    await world.send(world.owner, "mitski wake up")
    assert not world.app.away.asleep(world.guild.id)
    assert world.sent_text() == ["mm im up"]


async def test_quiet_command_from_the_log_channel(world):
    log = FakeChannel(world.client, world.guild, "her-log")
    world.app.cfg.LOG_CHANNEL = log.id
    await world.app.router.route(FakeMessage(log, world.owner, f"!quiet 15 {world.guild.id}"))
    await settle(world.app)
    assert world.app.away.is_quiet(world.guild.id)
    assert "completely quiet in the server for 15 min" in log.messages[-1].content


async def test_two_quick_messages_get_one_reply(world):
    anna = world.people["anna"]
    world.replies.extend(["one answer for both", "a second answer"])
    first = world.say(anna, "mitski")
    second = world.say(anna, "do u play valorant", to_her=False)
    await world.app.router.route(first)
    await world.app.router.route(second)
    await settle(world.app)
    assert world.sent_text() == ["one answer for both"]


async def test_typing_is_tracked_but_not_for_ignored_users(world):
    anna, bob = world.people["anna"], world.people["bob"]
    world.app.cfg.ignored.add(bob.id)
    world.app.router.typing(world.channel, anna)
    world.app.router.typing(world.channel, bob)
    assert list(world.app.state.last_typing) == [(world.channel.id, anna.id)]


async def test_her_own_messages_never_trigger_a_reply(world):
    await world.send(world.her, "mitski talking to myself")
    assert world.prompts == []
