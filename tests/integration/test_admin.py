import yaml

from mitski.admin.commands import CHUNK, MEMORY_COMMANDS, pieces
from mitski.admin.registry import GROUPS
from mitski.config import Settings
from mitski.testing.fakes import FakeChannel, FakeDM, FakeMessage, settle


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


async def test_every_command_has_a_short_alias_and_no_word_means_two_things():
    words = [w for _t, cmds in GROUPS for c in cmds for w in (c.name, *c.aliases)]
    assert len(words) == len(set(words))
    for _title, cmds in GROUPS:
        for c in cmds:
            assert any(len(a) <= 3 for a in c.aliases), c.name


async def test_every_command_has_a_handler(world):
    admin = world.app.admin
    for _title, cmds in GROUPS:
        for c in cmds:
            assert c.name in MEMORY_COMMANDS or hasattr(admin, f"_{c.name}"), c.name


async def test_aliases_run_the_same_command(world):
    new = FakeChannel(world.client, world.guild, "memes")
    out = await command(world, world.channel, f"!AC {new.id}")
    assert f"+ #memes `{new.id}`" in out
    assert "#memes" in await command(world, world.channel, "!lc")
    assert "she's free for 20 min" in await command(world, world.channel, "!fr 20")


async def test_memory_commands_answer_to_their_aliases(world):
    anna = world.people["anna"]
    world.app.memory.people[str(anna.id)] = world.app.memory._migrate({"name": "anna", "first_seen": 0, "last_seen": 0})
    out = await command(world, world.channel, "!n anna likes tea")
    assert "likes tea" in out
    assert "usage" in await command(world, world.channel, "!m")


async def test_feedback_no_longer_lists_every_command(world):
    new = FakeChannel(world.client, world.guild, "memes")
    out = await command(world, world.channel, f"!addchannel {new.id}")
    assert out == f"+ #memes `{new.id}` (the server)"
    assert "!stats" not in out


async def test_help_lists_commands_aliases_and_descriptions_with_the_live_prefix(world):
    world.app.cfg.COMMAND_PREFIX = "?"
    msg = FakeMessage(world.channel, world.owner, "?h")
    before = len(world.channel.messages)
    await world.app.router.route(msg)
    sent = world.channel.messages[before:]
    text = "\n".join(m.content for m in sent)
    assert all(len(m.content) <= 2000 for m in sent)
    for _title, cmds in GROUPS:
        for c in cmds:
            assert f"?{c.name}" in text
            assert all(f"`?{a}`" in text for a in c.aliases)
            assert c.about in text
    assert "`!" not in text


async def test_strangers_are_ignored_everywhere(world):
    bob = world.people["bob"]
    dm = FakeDM(world.client, bob)
    admin = log_channel(world)
    for channel in (world.channel, admin, dm):
        for text in ("!stats", "!help", f"!ac {channel.id}", "!mem bob", "!forgetme", "!quiet 5", "!prefix ?"):
            await world.app.router.route(FakeMessage(channel, bob, text))
    await settle(world.app)
    assert world.client.sent == []
    assert world.app.cfg.COMMAND_PREFIX == "!"
    assert bob.id not in world.app.cfg.memory_optout
    assert not world.app.away.state(world.guild.id)


async def test_nobody_can_use_commands_without_an_owner(world):
    world.app.owner.id = 0
    await world.app.router.route(FakeMessage(log_channel(world), world.owner, "!stats"))
    assert world.client.sent == []


async def test_commands_only_work_in_the_command_channel_when_one_is_set(world):
    room = FakeChannel(world.client, world.guild, "her-commands")
    logs = log_channel(world)
    world.app.cfg.COMMAND_CHANNEL = room.id
    dm = FakeDM(world.client, world.owner)
    for channel in (world.channel, logs, dm):
        await world.app.router.route(FakeMessage(channel, world.owner, "!stats"))
    await settle(world.app)
    assert world.client.sent == []
    assert "background tasks running" in await command(world, room, "!stats")


async def test_commands_work_anywhere_without_a_command_channel(world):
    logs = log_channel(world)
    dm = FakeDM(world.client, world.owner)
    for channel in (world.channel, logs, dm):
        assert "she's free" in await command(world, channel, "!free 5")


async def test_the_log_channel_still_gets_the_log_with_commands_elsewhere(world):
    logs = log_channel(world)
    world.app.cfg.COMMAND_CHANNEL = FakeChannel(world.client, world.guild, "her-commands").id
    await world.app.relay.post("hello log")
    assert logs.messages[-1].content == "hello log"


async def test_she_doesnt_chat_in_the_log_channel(world):
    world.app.cfg.save_list("CHANNELS", [])
    logs = log_channel(world)
    world.app.cfg.channels.add(logs.id)
    world.replies.append("hii")
    await world.app.router.route(FakeMessage(logs, world.owner, "mitski hey", mentions=[world.her]))
    await settle(world.app)
    assert world.client.sent == []


async def test_a_command_is_not_chatted_about(world):
    world.replies.append("hii")
    await world.send(world.people["anna"], "!stats")
    assert world.client.sent == []
    assert world.prompts == []


async def test_commands_and_their_replies_stay_out_of_what_she_reads(world):
    await world.send(world.owner, "!free 5", to_her=False)
    feedback = world.channel.messages[-1]
    assert "she's free" in feedback.content
    assert not world.app.messages.usable(feedback)
    assert not world.app.messages.usable(world.channel.messages[-2])
    world.replies.append("hii")
    await world.send(world.people["anna"], "mitski hey")
    assert "she's free" not in str(world.prompts[-1])
    assert "!free" not in str(world.prompts[-1])


async def test_prefix_changes_live_and_is_saved(world):
    assert "the prefix is `!`" in await command(world, world.channel, "!prefix")
    assert "the prefix is now `?`" in await command(world, world.channel, "!px ?")
    assert saved(world, "COMMAND_PREFIX") == "?"
    before = len(world.channel.messages)
    await world.app.router.route(FakeMessage(world.channel, world.owner, "!free 5", mentions=[]))
    await settle(world.app)
    assert len(world.channel.messages) == before + 1
    assert "she's free" in await command(world, world.channel, "?free 5")
    reloaded = Settings.load(world.app.cfg.paths)
    assert reloaded.COMMAND_PREFIX == "?"


async def test_prefix_keeps_the_comment_and_case_and_survives_yaml_symbols(world):
    for prefix in ("#", "[", "m!", "M!", "'", '"', "\\", "%", "&*"):
        await world.app.admin.dispatch(
            FakeMessage(world.channel, world.owner, f"{world.app.cfg.COMMAND_PREFIX}px {prefix}")
        )
        assert saved(world, "COMMAND_PREFIX") == prefix
        assert world.app.cfg.get("COMMAND_PREFIX") == prefix
    assert await world.app.admin.dispatch(FakeMessage(world.channel, world.owner, "&*FREE 5"))
    world.app.cfg.save_list("CHANNELS", [world.channel.id])
    assert saved(world, "COMMAND_PREFIX") == "&*"
    assert "# what commands start with" in world.app.cfg.paths.config.read_text(encoding="utf-8")


async def test_bad_prefixes_are_refused(world):
    for bad, why in (("abc", "symbol"), ("!!!!!!", "characters"), ("a b", "spaces"), ("`", "backticks")):
        assert why in await command(world, world.channel, f"!prefix {bad}")
        assert world.app.cfg.COMMAND_PREFIX == "!"


async def test_a_bad_prefix_in_the_config_falls_back(paths):
    for bad in ("", "   ", "word", "a b"):
        assert Settings.from_dict({"COMMAND_PREFIX": bad}, paths).COMMAND_PREFIX == "!"
    assert Settings.from_dict({"COMMAND_PREFIX": None}, paths).COMMAND_PREFIX == "!"


async def test_owner_forgetme_works_and_keeps_the_two_word_form(world):
    assert "forgot" in await command(world, world.channel, "!forget me")
    assert world.owner.id in world.app.cfg.memory_optout
    assert saved(world, "MEMORY_OPTOUT") == [world.owner.id]
    assert "remember" in await command(world, world.channel, "!remember me")
    assert world.owner.id not in world.app.cfg.memory_optout


async def test_long_replies_split_on_line_breaks():
    text = "\n\n".join("x" * 1000 for _ in range(3)) + "\n" + "y" * 4000
    parts = list(pieces(text))
    assert all(0 < len(p) <= CHUNK for p in parts)
    assert parts[0] == "x" * 1000
    assert "".join(parts).replace("\n", "") == text.replace("\n", "")
