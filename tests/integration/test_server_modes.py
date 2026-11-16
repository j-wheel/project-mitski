import json

import pytest

from mitski.chat.policy import (
    ADULT_NOTE,
    NORMAL,
    SAFE,
    SAFE_SERVER_NOTE,
    UNRESTRICTED,
    UNRESTRICTED_NOTE,
    ContentPolicy,
    sexualizes_a_minor,
    tame,
    tone_problem,
)
from mitski.testing.fakes import FakeDM, FakeMessage, settle


def mode(world, value):
    world.app.policy.set_mode(world.guild.id, value)


async def command(world, text, channel=None):
    channel = channel or world.channel
    await world.app.router.route(FakeMessage(channel, world.owner, f"{world.app.cfg.COMMAND_PREFIX}{text}"))
    await settle(world.app)
    return world.client.sent[-1].content


@pytest.mark.parametrize(
    ("line", "kind"),
    [
        ("what the fuck", "vulgar"),
        ("fuuuck this", "vulgar"),
        ("thats bullshit", "vulgar"),
        ("wtf bro", "vulgar"),
        ("i will end you", "a threat"),
        ("ima find you", "a threat"),
        ("kys", "a threat"),
        ("ur dead", "a threat"),
        ("hey cutie", "flirting"),
        ("ur so hot", "flirting"),
        ("kiss me", "flirting"),
        ("😏", "flirting"),
        ("ur such a loser", "bullying"),
        ("you are so stupid", "bullying"),
        ("shut up noob", "bullying"),
    ],
)
def test_what_safe_mode_catches(line, kind):
    assert tone_problem(line) == kind


@pytest.mark.parametrize(
    "line",
    [
        "class was so long",
        "pass me the notes",
        "that movie was great",
        "hello how are u",
        "this game is so hard",
        "lol",
    ],
)
def test_normal_chat_isnt_caught(line):
    assert tone_problem(line) is None


def test_her_persona_loses_the_edgy_parts_for_safe_servers():
    persona = (
        "You're from Portugal. You roast your friends and make fake threats. Sometimes you get flirty. You like cs."
    )
    assert tame(persona) == "You're from Portugal. You like cs."


def test_a_note_about_a_minor_survives_that():
    assert "minor" in tame("They're a minor: no flirting or anything romantic, ever.")


def test_nothing_sexual_about_a_minor():
    assert sexualizes_a_minor("sex with a 15 year old")
    assert not sexualizes_a_minor("sex is fun")
    assert not sexualizes_a_minor("my kid is 15")


async def test_every_server_starts_safe(world):
    assert world.app.policy.mode(world.channel) == SAFE


async def test_servers_she_joins_later_are_safe_too(world):
    assert world.app.policy.mode_in(type(world.guild)("new place")) == SAFE


async def test_a_mode_survives_a_restart(world):
    mode(world, UNRESTRICTED)
    again = ContentPolicy(world.app)
    again.load()
    assert again.mode(world.channel) == UNRESTRICTED
    mode(world, SAFE)
    assert json.loads(world.app.policy.file.path.read_text(encoding="utf-8")) == {}


async def test_safe_mode_rewrites_a_vulgar_reply(world):
    world.replies += ["what the fuck is up", "not much, how are u"]
    await world.send(world.people["anna"], "mitski hey")
    assert world.sent_text() == ["not much, how are u"]
    assert "Say it again clean and kind" in world.prompts[-1]


async def test_safe_mode_stays_quiet_if_she_cant_do_it_clean(world):
    world.replies += ["ima find you", "shut up noob"]
    await world.send(world.people["anna"], "mitski hey")
    assert world.sent_text() == []


async def test_safe_mode_is_in_her_prompt_and_the_edgy_persona_isnt(world):
    world.app.cfg.PERSONA = "You're cool. You make fake threats and flirt a lot."
    world.replies.append("hii")
    await world.send(world.people["anna"], "mitski hey")
    assert SAFE_SERVER_NOTE in world.prompts[0] and "fake threats" not in world.prompts[0]


async def test_the_sender_drops_what_gets_past_everything_else(world):
    sent = await world.app.sender.send(world.channel, ["hello", "hey babe", "go die"])
    assert [m.content for m in sent] == ["hello"]


async def test_the_notes_model_can_turn_a_reply_down(world, monkeypatch):
    world.app.cfg.SAFETY_REVIEW = True
    verdicts = [{"ok": False}, {"ok": True}]

    async def ask_json(system, user, schema, *args, **kwargs):
        return verdicts.pop(0) if "ok" in schema["properties"] and len(schema["properties"]) == 1 else None

    monkeypatch.setattr(world.app.helper, "ask_json", ask_json)
    world.replies += ["seems fine to the word list", "actually fine"]
    await world.send(world.people["anna"], "mitski hey")
    assert world.sent_text() == ["actually fine"]


async def test_no_second_opinion_outside_safe_mode(world, monkeypatch):
    called = []

    async def ask_json(*args, **kwargs):
        called.append(args)

    world.app.cfg.SAFETY_REVIEW = True
    monkeypatch.setattr(world.app.helper, "ask_json", ask_json)
    mode(world, NORMAL)
    assert not await world.app.policy.judged_unsafe(["hi"], world.channel)
    assert called == []


async def test_normal_mode_lets_her_be_herself(world):
    mode(world, NORMAL)
    world.replies.append("what the fuck is up")
    await world.send(world.people["anna"], "mitski hey")
    assert world.sent_text() == ["what the fuck is up"]
    assert SAFE_SERVER_NOTE not in world.prompts[0]


async def test_pg_18_stays_out_of_a_safe_server_even_with_all_channels(world):
    world.app.cfg.ADULT_CONTENT = "all_channels"
    world.channel.nsfw = True
    assert not world.app.policy.adult_ok(world.channel)
    sent = await world.app.sender.send(world.channel, ["send nudes"])
    assert sent == []


async def test_normal_follows_adult_content(world):
    mode(world, NORMAL)
    world.app.cfg.ADULT_CONTENT = "all_channels"
    assert world.app.policy.adult_ok(world.channel)
    assert world.app.policy.note(world.channel) == ADULT_NOTE


async def test_unrestricted_changes_her_prompt_and_lets_it_through(world):
    mode(world, UNRESTRICTED)
    world.app.cfg.ADULT_CONTENT = "all_channels"
    world.replies.append("fuck that, come here cutie")
    await world.send(world.people["anna"], "mitski hey")
    assert world.sent_text() == ["fuck that, come here cutie"]
    assert UNRESTRICTED_NOTE in world.prompts[0]


async def test_unrestricted_still_follows_adult_content_for_sexual_stuff(world):
    mode(world, UNRESTRICTED)
    world.app.cfg.ADULT_CONTENT = "nsfw_channels"
    assert not world.app.policy.adult_ok(world.channel)
    assert await world.app.sender.send(world.channel, ["send nudes"]) == []
    assert len(await world.app.sender.send(world.channel, ["what the fuck"])) == 1


async def test_nothing_explicit_or_flirty_around_a_minor_in_any_mode(world, monkeypatch):
    world.app.cfg.ADULT_CONTENT = "all_channels"
    anna = world.people["anna"]
    monkeypatch.setattr(world.app.ages, "is_minor", lambda u: getattr(u, "id", u) == anna.id)
    world.app.state.chan_log[world.channel.id].append((1, anna.id))
    for level in (NORMAL, UNRESTRICTED):
        mode(world, level)
        sent = await world.app.sender.send(world.channel, ["send nudes", "hey cutie", f"hello {level}"])
        assert [m.content for m in sent] == [f"hello {level}"]
        assert not world.app.policy.adult_ok(world.channel, minors=True)


async def test_a_note_about_minors_replaces_the_unrestricted_one(world):
    mode(world, UNRESTRICTED)
    assert UNRESTRICTED_NOTE not in world.app.policy.note(world.channel, minors=True)


async def test_nothing_sexual_about_a_minor_even_when_unrestricted(world):
    mode(world, UNRESTRICTED)
    world.app.cfg.ADULT_CONTENT = "all_channels"
    assert await world.app.sender.send(world.channel, ["sex with a 15 year old"]) == []


async def test_dms_have_no_mode_and_arent_held_to_safe(world):
    anna = world.people["anna"]
    dm = FakeDM(world.client, anna)
    assert world.app.policy.mode(dm) is None
    assert [m.content for m in await world.app.sender.send(dm, ["what the fuck", "send nudes"])] == ["what the fuck"]


async def test_minors_are_still_protected_in_dms(world, monkeypatch):
    anna = world.people["anna"]
    dm = FakeDM(world.client, anna)
    monkeypatch.setattr(world.app.ages, "is_minor", lambda u: getattr(u, "id", u) == anna.id)
    msg = FakeMessage(dm, anna, "hi")
    sent = await world.app.sender.send(dm, ["hey cutie", "hello"], reply_to=msg)
    assert [m.content for m in sent] == ["hello"]


async def test_no_flirty_reaction_in_a_safe_server(world, monkeypatch):
    msg = FakeMessage(world.channel, world.people["anna"], "lol")

    async def pick(_msg, _quick=False):
        return "😘"

    monkeypatch.setattr(world.app.reactions, "pick", pick)
    await world.app.reactions.react(msg)
    assert msg.reactions == []


async def test_gifs_are_capped_at_pg13_in_a_safe_server(world):
    world.app.cfg.GIF_RATING = "r"
    assert world.app.policy.gif_rating(world.channel) == "pg-13"
    mode(world, NORMAL)
    assert world.app.policy.gif_rating(world.channel) == "r"


async def test_gif_rating_isnt_raised(world):
    world.app.cfg.GIF_RATING = "g"
    assert world.app.policy.gif_rating(world.channel) == "g"


async def test_modeset(world):
    out = await command(world, f"modeset normal {world.guild.id}")
    assert "is now **normal**" in out and world.app.policy.mode(world.channel) == NORMAL
    await command(world, f"ms safe {world.guild.id}")
    assert world.app.policy.mode(world.channel) == SAFE


async def test_modeset_needs_a_mode_and_a_server(world):
    assert "usage:" in await command(world, "modeset normal")
    assert "usage:" in await command(world, f"modeset banana {world.guild.id}")
    assert world.app.policy.mode(world.channel) == SAFE


async def test_modeset_on_a_server_she_isnt_in(world):
    assert "she isn't in" in await command(world, "modeset normal 123456789012345678")


async def test_view_and_list_modes(world):
    mode(world, UNRESTRICTED)
    assert "is **unrestricted**" in await command(world, "mode")
    assert "is **unrestricted**" in await command(world, f"mo {world.guild.id}")
    listing = await command(world, "modes")
    assert "**safe**" in listing and f"unrestricted · {world.guild.name}" in listing


async def test_only_her_owner_can_change_a_mode(world):
    bob = world.people["bob"]
    world.app.cfg.amod.add(bob.id)
    msg = FakeMessage(world.channel, bob, f"{world.app.cfg.COMMAND_PREFIX}modeset unrestricted {world.guild.id}")
    await world.app.router.route(msg)
    await settle(world.app)
    assert world.app.policy.mode(world.channel) == SAFE
