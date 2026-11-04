from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

import discord
import pytest

from mitski.social import routine as rt
from mitski.testing.fakes import FakeChannel, FakeDM, FakeMessage, settle

# busy she only looks now and then


class MovingClock:
    """Every look at the clock moves it a minute, so a wait for her to look actually ends."""

    def __init__(self, step=60):
        self.when = datetime(2026, 11, 2, 20, 0, tzinfo=UTC)
        self.step = timedelta(seconds=step)
        self.late = False

    def now(self):
        self.when += self.step
        return self.when


@pytest.fixture
def busy_world(world):
    world.app.clock = MovingClock()
    routine = world.app.routine
    routine.on = True
    routine.days = {}
    routine.week = rt.Week(None, None, "", (), (0, 0), (), (0, 0))
    routine.set_busy(240, "out with a friend")
    return world


async def test_she_doesnt_see_a_ping_right_away_when_busy(busy_world):
    world = busy_world
    world.replies.append("sorry just saw this")
    await world.send(world.people["anna"], "mitski u there")
    assert world.sent_text() == ["sorry just saw this"]
    assert world.app.routine.looking()
    assert "out with a friend" in world.prompts[0]


async def test_a_long_wait_tells_her_she_saw_it_late(busy_world):
    world = busy_world
    world.app.routine.next_look = world.app.routine.stamp() + 3000
    world.replies.append("sorry")
    await world.send(world.people["anna"], "mitski u there")
    assert "You only just saw this" in world.prompts[0]
    assert "because you were out with a friend" in world.prompts[0]


async def test_while_she_is_looking_there_is_no_wait(busy_world):
    world = busy_world
    world.app.routine.look()
    world.app.routine.around_until += 100000
    world.replies.append("hii")
    await world.send(world.people["anna"], "mitski hi")
    assert world.sent_text() == ["hii"]
    assert "You only just saw this" not in world.prompts[0]


async def test_waiting_doesnt_block_the_channel(busy_world):
    world = busy_world
    locks = []
    original = world.app.routine.notice_at

    def notice(kind, owner=False):
        locks.append(world.app.state.channel_locks.get(world.channel.id))
        return original(kind, owner)

    world.app.routine.notice_at = notice
    world.replies.append("hi")
    await world.send(world.people["anna"], "mitski hi")
    assert locks == [None]


async def test_she_answers_everything_said_while_she_was_away_together(busy_world):
    world = busy_world
    world.replies.append("ok ok im here")
    anna = world.people["anna"]
    await world.app.router.route(world.say(anna, "mitski"))
    await world.app.router.route(world.say(anna, "hello??", to_her=False))
    await world.app.router.route(world.say(anna, "where did u go", to_her=False))
    await settle(world.app)
    assert world.sent_text() == ["ok ok im here"]
    assert "where did u go" in world.prompts[0]


async def test_she_doesnt_join_in_by_herself_while_busy(busy_world):
    world = busy_world
    assert world.app.ambient.should_join(world.channel.id) is False
    msg = world.say(world.people["anna"], "who won?", to_her=False)
    world.app.pipeline.join_in(world.channel, msg)
    await settle(world.app)
    assert world.sent_text() == []


async def test_an_old_chat_message_is_let_go_but_an_old_dm_is_not(busy_world):
    world = busy_world
    anna = world.people["anna"]
    world.replies.append("sorry i was out")
    dm = FakeDM(world.client, anna)
    msg = FakeMessage(dm, anna, "hey u around?")
    msg.created_at = discord.utils.utcnow() - timedelta(hours=5)
    world.app.routine.next_look = world.app.routine.stamp() + 3000
    await world.app.router.route(msg)
    await settle(world.app)
    assert [m.content for m in world.client.sent] == ["sorry i was out"]

    world.client.sent.clear()
    old = world.say(anna, "lol", to_her=False)
    old.created_at = discord.utils.utcnow() - timedelta(minutes=30)
    world.app.addressing.engage(world.channel.id, anna.id, refill=True)
    await world.app.router.route(old)
    await settle(world.app)
    assert world.sent_text() == []


async def test_a_ping_from_hours_ago_is_let_go(busy_world):
    world = busy_world
    msg = world.say(world.people["anna"], "mitski u there")
    msg.created_at = discord.utils.utcnow() - timedelta(hours=5)
    world.app.routine.next_look = world.app.routine.stamp() + 3000
    await world.app.router.route(msg)
    await settle(world.app)
    assert world.sent_text() == []
    assert world.prompts == []


async def test_changing_spell_updates_her_status_and_the_log(world, monkeypatch):
    routine = world.app.routine
    routine.on = True
    routine.days = {}
    routine.week = rt.Week(None, None, "", (), (0, 0), (), (0, 0))
    log = FakeChannel(world.client, world.guild, "her-log")
    world.app.cfg.LOG_CHANNEL = log.id
    await routine.tick()
    assert world.client.presence is None
    routine.set_busy(30, "out shopping")
    await routine.tick()
    assert world.client.presence["status"] == discord.Status.idle
    await settle(world.app)
    assert any("out shopping" in m.content for m in log.messages)
    routine.set_free(30)
    await routine.tick()
    assert any("free" in m.content for m in log.messages)


async def test_admin_commands_show_and_change_the_routine(world):
    routine = world.app.routine
    routine.on = True
    routine.days = {}
    routine.week = rt.Week(None, None, "", (), (0, 0), (), (0, 0))
    log = FakeChannel(world.client, world.guild, "her-log")
    world.app.cfg.LOG_CHANNEL = log.id
    await world.app.router.route(FakeMessage(log, world.owner, "!busy 45 at the dentist"))
    assert routine.doing() == "at the dentist"
    assert "at the dentist for 45 min" in log.messages[-1].content
    await world.app.router.route(FakeMessage(log, world.owner, "!routine"))
    assert "at the dentist until" in log.messages[-1].content
    await world.app.router.route(FakeMessage(log, world.owner, "!free 20"))
    assert routine.free


# dms she starts herself


@pytest.fixture
def dm_world(world, monkeypatch):
    opened = []

    async def fake_open(user, channel, promise=None):
        opened.append(user)

    monkeypatch.setattr(world.app.dms, "open", fake_open)
    world.app.cfg.DM_CHANCE = 1.0
    world.app.cfg.DM_MIN_EXCHANGES = 1
    return world, opened


def friend(world, user):
    world.client.friends.append(NS(user=user))


async def test_friends_only_dms_friends(dm_world):
    world, opened = dm_world
    anna, bob = world.people["anna"], world.people["bob"]
    world.app.cfg.DM_ENABLED_FRIEND = True
    friend(world, anna)
    world.app.dms.note_exchange(anna, world.channel)
    world.app.dms.note_exchange(bob, world.channel)
    await settle(world.app)
    assert opened == [anna]


async def test_friends_being_off_means_no_dms(dm_world):
    world, opened = dm_world
    friend(world, world.people["anna"])
    world.app.dms.note_exchange(world.people["anna"], world.channel)
    await settle(world.app)
    assert opened == []


async def test_dm_enabled_still_means_anyone(dm_world):
    world, opened = dm_world
    world.app.cfg.DM_ENABLED = True
    world.app.dms.note_exchange(world.people["bob"], world.channel)
    await settle(world.app)
    assert opened == [world.people["bob"]]


async def test_she_never_starts_a_dm_with_a_known_minor(dm_world):
    world, opened = dm_world
    anna = world.people["anna"]
    world.app.cfg.DM_ENABLED = True
    world.app.cfg.DM_ENABLED_FRIEND = True
    friend(world, anna)
    world.app.ages.is_minor = lambda user: user is anna
    world.app.dms.note_exchange(anna, world.channel)
    await settle(world.app)
    assert opened == []
    assert world.app.dms.may_start_dm(world.people["bob"]) is True


async def test_she_doesnt_start_dms_while_busy(dm_world):
    world, opened = dm_world
    anna = world.people["anna"]
    world.app.cfg.DM_ENABLED_FRIEND = True
    friend(world, anna)
    routine = world.app.routine
    routine.on = True
    routine.set_busy(60, "out")
    world.app.dms.note_exchange(anna, world.channel)
    await settle(world.app)
    assert opened == []


async def test_unfriending_before_the_dm_goes_out_cancels_it(world):
    anna = world.people["anna"]
    world.app.cfg.DM_ENABLED_FRIEND = True
    calls = []
    anna.create_dm = lambda: calls.append(1)
    await world.app.dms.open(anna, world.channel)
    assert calls == []
