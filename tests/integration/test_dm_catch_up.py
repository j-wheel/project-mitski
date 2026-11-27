from datetime import timedelta

from mitski.testing.fakes import FakeDM, FakeMessage, settle


def dm_from(world, person, *texts, hours_ago=2.0, hers=False):
    dm = getattr(person, "_dm", None) or FakeDM(world.client, person)
    person._dm = dm
    if dm not in world.client.private_channels:
        world.client.private_channels.append(dm)
    for text in texts:
        msg = FakeMessage(dm, world.client.user if hers else person, text)
        msg.created_at -= timedelta(hours=hours_ago)
    return dm


def sent_in(world, dm):
    return [m.content for m in world.client.sent if m.channel is dm]


async def catch_up(world):
    await world.app.dms.catch_up()
    await settle(world.app)


async def test_she_answers_a_dm_that_came_in_while_she_was_offline(world):
    anna = world.people["anna"]
    dm = dm_from(world, anna, "hey are u coming tonight?", hours_ago=3)
    world.replies.append("omg just saw this, ya im coming")
    await catch_up(world)
    assert sent_in(world, dm) == ["omg just saw this, ya im coming"]
    assert "You were offline and only just saw this, about 3 hours after" in world.prompts[-1]


async def test_not_if_she_was_the_last_one_to_message(world):
    anna = world.people["anna"]
    dm_from(world, anna, "hey are u coming tonight?", hours_ago=4)
    dm = dm_from(world, anna, "ya ill be there", hours_ago=3, hers=True)
    await catch_up(world)
    assert sent_in(world, dm) == []


async def test_not_if_its_too_old(world):
    dm = dm_from(world, world.people["anna"], "hey", hours_ago=world.app.cfg.DM_CATCH_UP_HOURS + 5)
    await catch_up(world)
    assert sent_in(world, dm) == []


async def test_not_people_she_ignores(world):
    anna = world.people["anna"]
    world.app.cfg.ignored.add(anna.id)
    dm = dm_from(world, anna, "hellooo", hours_ago=1)
    await catch_up(world)
    assert sent_in(world, dm) == []


async def test_not_a_message_request_she_never_answered(world):
    anna = world.people["anna"]
    dm = dm_from(world, anna, "hey cutie", hours_ago=1)
    dm.is_message_request = lambda: True
    await catch_up(world)
    assert sent_in(world, dm) == []


async def test_turned_off_means_no_catching_up(world):
    world.app.cfg.DM_CATCH_UP = False
    dm = dm_from(world, world.people["anna"], "hey", hours_ago=1)
    await catch_up(world)
    assert sent_in(world, dm) == []


async def test_she_catches_up_on_a_few_at_most(world):
    world.app.cfg.DM_CATCH_UP_MAX = 1
    a = dm_from(world, world.people["anna"], "hey", hours_ago=5)
    b = dm_from(world, world.people["bob"], "yo", hours_ago=1)
    world.replies.extend(["heyy", "yoo"])
    await catch_up(world)
    assert sent_in(world, b) and not sent_in(world, a)


async def test_old_dms_are_skipped_without_even_reading_them(world):
    import discord

    anna = world.people["anna"]
    dm = dm_from(world, anna, "hey", hours_ago=1)
    old = discord.utils.time_snowflake(discord.utils.utcnow() - timedelta(days=30))
    dm.last_message_id = old
    read = []
    real = dm.history

    def history(limit=100):
        read.append(limit)
        return real(limit)

    dm.history = history
    await catch_up(world)
    assert read == [] and sent_in(world, dm) == []


async def test_not_if_she_already_answered_since_she_came_online(world):
    anna = world.people["anna"]
    dm = dm_from(world, anna, "hey u up?", hours_ago=1)
    last = dm.messages[-1]
    world.app.sender.last_sent[dm.id] = last.id + 1
    await catch_up(world)
    assert sent_in(world, dm) == []
