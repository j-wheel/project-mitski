import yaml

from mitski.testing.fakes import FakeChannel, FakeMessage, settle


def log_channel(world):
    channel = FakeChannel(world.client, world.guild, "her-log")
    world.app.cfg.LOG_CHANNEL = channel.id
    return channel


async def command(world, channel, text, author=None):
    msg = FakeMessage(channel, author or world.owner, text)
    await world.app.router.route(msg)
    await settle(world.app)
    return channel.messages[-1].content


def saved(world, key):
    return yaml.safe_load(world.app.cfg.paths.config.read_text(encoding="utf-8")).get(key)


async def test_addchannel_takes_effect_live_and_is_saved(world):
    admin = log_channel(world)
    new = FakeChannel(world.client, world.guild, "memes")
    out = await command(world, admin, f"!addchannel {new.id}")
    assert f"+ #memes `{new.id}`" in out
    assert new.id in world.app.cfg.channels
    assert saved(world, "CHANNELS") == [new.id]
    assert world.app.messages.allowed_channel(new)


async def test_delchannel_forgets_pending_replies(world):
    admin = log_channel(world)
    world.app.cfg.save_list("CHANNELS", [world.channel.id])
    world.app.state.waiting[(world.channel.id, 1)] = object()
    await command(world, admin, f"!delchannel {world.channel.id}")
    assert world.channel.id not in world.app.cfg.channels
    assert saved(world, "CHANNELS") == []
    assert not world.app.state.waiting


async def test_owner_cannot_be_ignored(world):
    admin = log_channel(world)
    out = await command(world, admin, f"!ignoreuser {world.owner.id}")
    assert "that's her owner" in out
    assert world.owner.id not in world.app.cfg.ignored


async def test_ignoring_someone_also_forgets_them(world):
    admin = log_channel(world)
    anna = world.people["anna"]
    world.app.memory.people[str(anna.id)] = {"name": "anna"}
    out = await command(world, admin, f"!ignoreuser {anna.id}")
    assert "forgot what she knew" in out
    assert anna.id in world.app.cfg.ignored
    assert str(anna.id) not in world.app.memory.people


async def test_commands_without_ids_explain_themselves(world):
    admin = log_channel(world)
    out = await command(world, admin, "!addchannel")
    assert "give me one or more ids" in out


async def test_sleep_exclude_list_is_shared_with_the_away_store(world):
    admin = log_channel(world)
    await command(world, admin, f"!sleepexclude {world.guild.id}")
    assert world.guild.id in world.app.away.exclude
    assert world.app.away.exclude is world.app.cfg.sleep_exclude


async def test_stats_reports_latency(world):
    world.replies.append("hii")
    await world.send(world.people["anna"], "mitski hey")
    admin = log_channel(world)
    out = await command(world, admin, "!stats")
    assert "time to first message" in out
    assert "llm calls per reply" in out


async def test_strangers_cannot_run_commands_in_dms_when_admins_are_set(world):
    world.app.memory.admins.add(world.owner.id)
    assert not world.app.admin.trusted(world.people["bob"])
    assert world.app.admin.trusted(world.owner)
