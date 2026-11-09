from types import SimpleNamespace

import yaml

from mitski.testing.fakes import FakeChannel, FakeDM, FakeMessage, FakeUser, settle, snowflake


async def command(world, channel, author, text):
    msg = FakeMessage(channel, author, f"{world.app.cfg.COMMAND_PREFIX}{text}")
    await world.app.router.route(msg)
    await settle(world.app)
    return [m.content for m in world.client.sent]


def saved(world, key):
    return yaml.safe_load(world.app.cfg.paths.config.read_text(encoding="utf-8")).get(key)


def role(world, name="mods"):
    made = SimpleNamespace(id=snowflake(), name=name)
    world.guild.roles.append(made)
    return made


async def test_muted_she_ignores_the_channel_and_unmuted_she_is_back(world):
    anna = world.people["anna"]
    out = await command(world, world.channel, world.owner, "mute")
    assert "muted in" in out[-1] and saved(world, "MUTED_CHANNELS") == [world.channel.id]
    before = len(world.client.sent)

    await world.send(anna, "mitski hiii")
    assert len(world.client.sent) == before and world.prompts == []

    await command(world, world.channel, world.owner, "unmute")
    assert saved(world, "MUTED_CHANNELS") == []
    world.replies.append("heyy")
    await world.send(anna, "mitski hiii")
    assert world.sent_text()[-1] == "heyy"


async def test_she_doesnt_learn_anything_while_muted(world):
    await command(world, world.channel, world.owner, "mute")
    await world.send(world.people["anna"], "i love tennis")
    assert str(world.people["anna"].id) not in world.app.memory.people


async def test_it_only_mutes_that_channel(world):
    await command(world, world.channel, world.owner, "mute")
    other = FakeChannel(world.client, world.guild, "other")
    world.app.cfg.channels.add(other.id)
    world.replies.append("yo")
    await world.app.router.route(FakeMessage(other, world.people["anna"], "mitski hiii"))
    await settle(world.app)
    assert any(m.channel is other and m.content == "yo" for m in world.client.sent)


async def test_muting_a_channel_mutes_its_threads(world):
    await command(world, world.channel, world.owner, "mute")
    thread = FakeChannel(world.client, world.guild, "a-thread")
    thread.parent_id = world.channel.id
    assert world.app.messages.muted(thread) and not world.app.messages.allowed_channel(thread)


async def test_a_reply_she_was_about_to_send_is_dropped(world):
    world.app.cfg.muted.add(world.channel.id)
    assert await world.app.sender.send(world.channel, ["hi"]) == []


async def test_a_mute_halfway_through_a_reply_stops_the_rest(world, monkeypatch):
    real = world.app.sender._post

    async def post_then_mute(out, line):
        await real(out, line)
        world.app.cfg.muted.add(world.channel.id)

    monkeypatch.setattr(world.app.sender, "_post", post_then_mute)
    sent = await world.app.sender.send(world.channel, ["one", "two", "three"])
    assert len(sent) == 1


async def test_mute_drops_pending_replies(world):
    world.app.state.waiting[(world.channel.id, 1)] = object()
    await command(world, world.channel, world.owner, "mute")
    assert (world.channel.id, 1) not in world.app.state.waiting


async def test_no_reaction_in_a_muted_channel(world, monkeypatch):
    msg = FakeMessage(world.channel, world.people["anna"], "lol")

    async def pick(_msg, _quick=False):
        return "😭"

    monkeypatch.setattr(world.app.reactions, "pick", pick)
    world.app.cfg.muted.add(world.channel.id)
    await world.app.reactions.react(msg)
    assert msg.reactions == []


async def test_no_typo_fix_in_a_muted_channel(world):
    world.app.cfg.muted.add(world.channel.id)
    assert world.app.sender._away(world.channel)


async def test_no_goodbye_in_a_muted_channel(world, monkeypatch):
    import time

    world.app.state.her_spoke[world.guild.id] = (world.channel, time.time())
    monkeypatch.setattr(world.app.away, "bye_chance", 1.1, raising=False)
    world.app.cfg.muted.add(world.channel.id)
    await world.app.sleep.say_bye(world.guild)
    assert world.prompts == [] and world.client.sent == []


async def test_a_reminder_from_a_muted_channel_comes_by_dm(world):
    anna = world.people["anna"]
    anna.dm_channel = FakeDM(world.client, anna)
    world.app.cfg.muted.add(world.channel.id)
    where = await world.app.scheduler._destination(SimpleNamespace(channel=world.channel.id), anna)
    assert where is anna.dm_channel


async def test_she_leaves_the_vc_when_it_gets_muted(world, monkeypatch):
    left = []

    async def leave(why, delay=0.0):
        left.append(why)

    voice = world.app.voice
    monkeypatch.setattr(voice, "leave", leave)
    voice.vc = SimpleNamespace(channel=world.channel)
    voice.session = SimpleNamespace(call=None, guild=world.guild.id)
    await command(world, world.channel, world.owner, "mute")
    voice.vc, voice.session = None, None
    assert left == ["muted"]


async def test_amod_user_can_mute_and_unmute(world):
    anna = world.people["anna"]
    await command(world, world.channel, world.owner, f"addp {anna.id}")
    assert saved(world, "AMOD") == [anna.id]
    await command(world, world.channel, anna, "mute")
    assert world.channel.id in world.app.cfg.muted
    await command(world, world.channel, anna, "unmute")
    assert world.channel.id not in world.app.cfg.muted


async def test_amod_role_can_mute(world):
    mods = role(world)
    bob = world.people["bob"]
    bob.roles = [mods]
    out = await command(world, world.channel, world.owner, f"addp {mods.id}")
    assert "role @mods" in out[-1]
    await command(world, world.channel, bob, "mute")
    assert world.channel.id in world.app.cfg.muted


async def test_someone_else_cant_mute_and_gets_no_answer(world):
    before = len(world.client.sent)
    await command(world, world.channel, world.people["bob"], "mute")
    assert world.channel.id not in world.app.cfg.muted
    assert len(world.client.sent) == before and world.prompts == []


async def test_amods_get_nothing_but_mute_and_unmute(world):
    anna = world.people["anna"]
    world.app.cfg.amod.add(anna.id)
    before = len(world.client.sent)
    bob = world.people["bob"]
    for text in ("help", "listchannels", f"addp {bob.id}", f"delp {anna.id}", "listp", f"ignoreuser {bob.id}", "stats"):
        await command(world, world.channel, anna, text)
    assert len(world.client.sent) == before
    assert bob.id not in world.app.cfg.amod and anna.id in world.app.cfg.amod
    assert bob.id not in world.app.cfg.ignored


async def test_amods_can_mute_outside_the_command_channel(world):
    anna = world.people["anna"]
    world.app.cfg.amod.add(anna.id)
    world.app.cfg.COMMAND_CHANNEL = 123
    await command(world, world.channel, anna, "mute")
    assert world.channel.id in world.app.cfg.muted


async def test_delp_takes_it_away(world):
    anna = world.people["anna"]
    await command(world, world.channel, world.owner, f"addp {anna.id}")
    await command(world, world.channel, world.owner, f"delp {anna.id}")
    assert saved(world, "AMOD") == [] and anna.id not in world.app.cfg.amod
    await command(world, world.channel, anna, "mute")
    assert world.channel.id not in world.app.cfg.muted


async def test_listp_shows_users_and_roles(world):
    mods = role(world)
    anna = world.people["anna"]
    world.app.cfg.amod |= {anna.id, mods.id}
    out = await command(world, world.channel, world.owner, "listp")
    assert "amods (2)" in out[-1] and "role @mods" in out[-1] and str(anna.id) in out[-1]


async def test_addp_with_nothing_asks_for_an_id(world):
    out = await command(world, world.channel, world.owner, "addp")
    assert "give me one or more ids" in out[-1]


async def test_mute_is_only_for_server_channels(world):
    anna = world.people["anna"]
    dm = FakeDM(world.client, anna)
    world.app.cfg.amod.add(anna.id)
    out = await command(world, dm, anna, "mute")
    assert "only works in server channels" in out[-1] and not world.app.cfg.muted


async def test_a_bot_on_the_list_cant_mute(world):
    robot = FakeUser("robot", bot=True)
    world.app.cfg.amod.add(robot.id)
    await command(world, world.channel, robot, "mute")
    assert world.channel.id not in world.app.cfg.muted
