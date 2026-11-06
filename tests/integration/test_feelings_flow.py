import json

import pytest

from mitski.llm.helper import Answer
from mitski.testing.world import build_world


@pytest.fixture
def world_sync(paths):
    return build_world(paths).script()


def remembering(world):
    world.app.cfg.MEMORY = True
    world.app.memory.enabled = True


def reply_prompt(world):
    """Her last reply prompt: memory notes run after replies and go through the same model."""
    return next(p for p in reversed(world.prompts) if "keep mitski's memory" not in p)


async def test_an_insult_changes_how_she_treats_them_right_away(world):
    remembering(world)
    anna = world.people["anna"]
    world.replies.extend(["wow ok", "what"])
    await world.send(anna, "mitski ur so annoying stfu")
    await world.send(anna, "mitski hello??")
    prompt = reply_prompt(world)
    assert "annoyed with them" in prompt and "irritated" in prompt


def hurt_of(world, person):
    d = world.app.memory.get(person.id)
    return d["regard"]["hurt"] if d and "regard" in d else 0


async def test_mid_chat_with_her_a_reply_to_someone_else_never_stings_her(world):
    remembering(world)
    anna, bob = world.people["anna"], world.people["bob"]
    world.replies.extend(["heyy", "lol"])
    await world.send(anna, "mitski hey")
    bobs = await world.send(bob, "anyone up for ranked", to_her=False)
    await world.send(anna, "ur so annoying stfu", to_her=False, reference=bobs)
    assert hurt_of(world, anna) == 0


async def test_answering_what_she_just_said_counts_as_said_to_her(world):
    remembering(world)
    anna = world.people["anna"]
    world.replies.extend(["heyy whats up", "wow ok"])
    await world.send(anna, "mitski hey")
    await world.send(anna, "ur so annoying stfu", to_her=False)
    assert hurt_of(world, anna) >= 8


async def test_once_someone_else_talks_in_between_it_isnt_an_answer_to_her_anymore(world):
    remembering(world)
    anna, bob = world.people["anna"], world.people["bob"]
    world.replies.extend(["heyy whats up", "lol"])
    await world.send(anna, "mitski hey")
    await world.send(bob, "lmao same", to_her=False)
    await world.send(anna, "ur so annoying stfu", to_her=False)
    assert hurt_of(world, anna) == 0


@pytest.mark.parametrize(
    ("text", "to_her"),
    [
        ("mitski ur so annoying", True),
        ("hey mitski ur so cute", True),
        ("ur so annoying mitski lol", True),
        ("lol mitski stfu", True),
        ("mitski is so annoying", False),
        ("i think mitski is cute", False),
        ("mitski's taste is mid", False),
        ("ngl mitski always does this", False),
    ],
)
def test_her_name_used_to_talk_to_her_not_about_her(world_sync, text, to_her):
    assert world_sync.app.addressing.named_directly(text) is to_her


async def test_talking_about_her_to_the_room_doesnt_sting(world):
    remembering(world)
    anna = world.people["anna"]
    world.replies.append("excuse me??")
    await world.send(anna, "mitski is so annoying", to_her=False)
    assert hurt_of(world, anna) == 0


async def test_banter_from_a_friend_doesnt_sour_anything(world):
    remembering(world)
    anna = world.people["anna"]
    world.replies.append("LMAO")
    await world.send(anna, "mitski ur so dumb lmao 💀")
    d = world.app.memory.get(anna.id)
    assert d["regard"]["hurt"] < 8 and "annoyed with them" not in reply_prompt(world)


async def test_her_memory_notes_judge_how_they_treated_her(world):
    remembering(world)
    anna = world.people["anna"]
    world.replies.extend(["omg yes", "ya"])
    notes = {
        "profile": {},
        "new_facts": [],
        "changed_facts": [],
        "wrong_facts": [],
        "her_nickname_for_them": "",
        "their_name_for_her": "",
        "bond": "",
        "conversation": {"summary": "", "mood": ""},
        "new_threads": [],
        "done_threads": [],
        "about_her": [],
        "feelings": [
            {"kind": "shared_interest", "intensity": 3, "evidence": "u like laufey too", "why": "loves laufey too"},
            {"kind": "insulted_her", "intensity": 3, "evidence": "u are the worst", "why": "made up, never said"},
        ],
    }
    asked = []

    async def ask(system, user_text, schema=None, max_tokens=700, think=False):
        asked.append((system, schema, max_tokens))
        return Answer(json.dumps(notes))

    world.app.helper.ask = ask
    await world.send(anna, "mitski omg u like laufey too?? shes my fav")
    if not asked:
        await world.app.memory.update(anna, world.channel)
    d = world.app.memory.get(anna.id)
    assert d["regard"]["like"] > 0 and d["regard"]["hurt"] == 0
    system, schema, max_tokens = asked[0]
    assert "feelings" in schema["required"] and "shared_interest" in system and max_tokens >= 1300
    assert any(e["kind"] == "shared_interest" for e in d["regard"]["events"])

    d["regard"]["like"] = 50
    await world.send(anna, "mitski whats up")
    prompt = reply_prompt(world)
    assert "You really like anna" in prompt and "loves laufey too" in prompt
