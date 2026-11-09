import json

import discord
import pytest

from mitski.social.status import STATUS_MAX, CustomStatus, fit, tidy, units


def written(text, emoji="🌧️"):
    return json.dumps({"status": text, "emoji": emoji}, ensure_ascii=False)


def custom_in(world):
    return next(a for a in world.client.presence["activities"] if a.type is discord.ActivityType.custom)


async def test_her_model_writes_a_status_and_it_goes_up(world):
    world.replies.append(written("cant be bothered today"))
    assert await world.app.custom_status.refresh()
    custom = custom_in(world)
    assert custom.name == "cant be bothered today" and custom.emoji.name == "🌧️"
    assert custom.to_dict()["state"] == "cant be bothered today"
    assert "custom status" in world.prompts[-1] and world.app.cfg.PERSONA in world.prompts[-1]


async def test_a_routine_update_doesnt_wipe_it(world):
    world.app.cfg.ACTIVITY_TYPE, world.app.cfg.ACTIVITY_TEXT = "playing", "Minecraft"
    world.replies.append(written("sleepy"))
    await world.app.custom_status.refresh()
    await world.app.profiles.apply()
    kinds = {a.type for a in world.client.presence["activities"]}
    assert kinds == {discord.ActivityType.playing, discord.ActivityType.custom}


async def test_a_long_one_is_cut_to_what_discord_allows_at_a_word(world):
    world.replies.append(written("word " * 60))
    assert await world.app.custom_status.refresh()
    text = world.app.custom_status.current[0]
    assert units(text) <= STATUS_MAX and text.endswith("word")


def test_emojis_inside_the_text_count_double():
    text = fit("😭" * 100)
    assert units(text) <= STATUS_MAX and len(text) <= 64


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("😭", "😭"),
        ("😭😭😭", "😭"),
        ("🌧️ ok", "🌧️"),
        ("🇵🇹", "🇵🇹"),
        ("👩‍💻", "👩‍💻"),
        ("👍🏽", "👍🏽"),
    ],
)
def test_it_takes_one_real_emoji(raw, expected):
    assert tidy({"status": "hi", "emoji": raw}) == ("hi", expected)


@pytest.mark.parametrize(
    "bad",
    [
        {"status": "hi", "emoji": ":sob:"},
        {"status": "hi", "emoji": ""},
        {"status": "", "emoji": "😭"},
        {"status": "😭", "emoji": "😭"},
        {"status": "go follow @anna", "emoji": "😭"},
        {"status": "check https://example.com", "emoji": "😭"},
        {"status": "join discord.gg/abc", "emoji": "😭"},
        {},
        None,
    ],
)
def test_things_that_cant_be_a_status(bad):
    assert tidy(bad) is None


def test_the_emoji_isnt_repeated_in_the_text():
    assert tidy({"status": '"ugh mondays 😭"', "emoji": "😭"}) == ("ugh mondays", "😭")


async def test_nonsense_from_the_model_keeps_the_old_one(world):
    world.replies.append(written("first one"))
    await world.app.custom_status.refresh()
    world.replies.append("not json at all")
    assert not await world.app.custom_status.refresh()
    assert world.app.custom_status.current[0] == "first one"


async def test_she_doesnt_repeat_herself(world):
    world.replies.append(written("same thing"))
    await world.app.custom_status.refresh()
    world.replies.append(written("Same Thing"))
    assert not await world.app.custom_status.refresh()
    assert "same thing" in world.prompts[-1]


async def test_the_model_being_down_doesnt_break_anything(world, monkeypatch):
    async def down(*args, **kwargs):
        raise RuntimeError("no server")

    monkeypatch.setattr(world.app.llm, "generate", down)
    assert not await world.app.custom_status.refresh()


async def test_a_new_one_is_due_in_an_hour_and_it_survives_a_restart(world):
    status = world.app.custom_status
    world.replies.append(written("still here"))
    await status.refresh()
    assert 3590 < status.due_in() <= 3600
    again = CustomStatus(world.app)
    again.load()
    assert again.current == status.current and 3590 < again.due_in() <= 3600


async def test_turned_off_there_is_no_custom_status(world):
    world.replies.append(written("hello"))
    await world.app.custom_status.refresh()
    world.app.cfg.STATUS_AUTO = False
    await world.app.profiles.apply()
    assert world.client.presence["activities"] == []


async def test_she_knows_what_her_status_says(world):
    world.replies.append(written("thinking about soup"))
    await world.app.custom_status.refresh()
    assert 'says "thinking about soup"' in world.app.profiles.own_status()


async def test_telling_her_to_clear_it_removes_it(world):
    world.replies.append(written("bye"))
    await world.app.custom_status.refresh()
    world.app.custom_status.clear()
    await world.app.profiles.apply()
    assert world.client.presence["activities"] == []
    assert world.app.custom_status.due_in() > 3500
