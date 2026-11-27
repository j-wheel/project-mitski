import pytest

from mitski.chat.patterns import LIST_LINE, SERVILE


def planner(world, **plan):
    async def ask_json(system, user, schema, max_tokens=400, think=False):
        if "reply_type" not in schema.get("properties", {}):
            return None
        return {
            "to_her": "her",
            "wants": "",
            "reply_type": "help",
            "length": "short",
            "ask": "none",
            "answer": "",
            "tools": [],
            **plan,
        }

    world.app.cfg.THINKING = True
    world.app.helper.ask_json = ask_json


RECIPE = "lemon drizzle: mix flour sugar eggs butter and lemon zest, bake 40 min at 180, pour lemon syrup over"


async def test_a_whole_recipe_gets_brushed_off_not_written_out(world):
    world.app.cfg.BRUSH_OFF_CHANCE = 1.0
    planner(world, ask="effort", answer=RECIPE)
    world.replies.append("lemon drizzle!! idk how to make it tho my mom does lol")
    await world.send(world.people["anna"], "mitski whats your favorite cake and can u give me a recipe")
    prompt = world.prompts[0]
    assert "not a helper" in prompt and "just google it" in prompt
    assert "What to tell them" not in prompt and "bake 40 min" not in prompt
    assert "answer retry" not in world.app.metrics.done[-1].events


async def test_or_she_just_gives_the_gist_she_knows(world):
    world.app.cfg.BRUSH_OFF_CHANCE = 0.0
    planner(world, ask="effort", answer=RECIPE)
    world.replies.append("lemon drizzle, its literally just sponge with lemon syrup on top")
    await world.send(world.people["anna"], "mitski can u give me a cake recipe")
    prompt = world.prompts[0]
    assert "just the gist you'd know offhand" in prompt and "No lists, no steps" in prompt
    assert "What to tell them" not in prompt


async def test_a_favour_gets_a_casual_bet_not_a_task_confirmation(world):
    planner(world, ask="favor", reply_type="other")
    world.replies.append("bet")
    await world.send(world.people["anna"], "mitski can u hop in vc")
    assert "not like an assistant confirming a task" in world.prompts[0]


async def test_assistant_speak_gets_redone_in_her_own_voice(world):
    world.replies.extend(["got it 😭\ni will remind him in 2hrs that his game is done", "ok ill bug him lol"])
    await world.send(world.people["anna"], "mitski remind sam in 2h his game is done")
    assert world.sent_text() == ["ok ill bug him lol"]
    assert world.app.metrics.done[-1].events["redo servile"] == 1


async def test_a_numbered_list_is_never_how_she_texts(world):
    world.replies.extend(["1. flour\n2. sugar\n3. eggs", "flour sugar eggs, the usual lol"])
    await world.send(world.people["anna"], "mitski what goes in a cake")
    assert world.sent_text() == ["flour sugar eggs, the usual lol"]


async def test_she_sometimes_doesnt_bother_googling(world):
    world.app.cfg.SKIP_LOOKUP_CHANCE = 1.0
    world.app.search.provider = "ddg"
    looked = []

    async def answer(query, said, name):
        looked.append(query)
        return "found it"

    world.app.search.answer = answer
    planner(world, ask="expert", reply_type="answer_question", tools=[{"tool": "search", "input": "boiling point"}])
    world.replies.append("no clue tbh")
    await world.send(world.people["anna"], "mitski whats the boiling point of mercury")
    assert looked == [] and "you're not looking it up right now" in world.prompts[0]


async def test_but_always_looks_it_up_when_asked_to(world):
    world.app.cfg.SKIP_LOOKUP_CHANCE = 1.0
    world.app.search.provider = "ddg"
    looked = []

    async def answer(query, said, name):
        looked.append(query)
        return "You googled it: 357°C"

    world.app.search.answer = answer
    planner(world, ask="expert", reply_type="answer_question", tools=[{"tool": "search", "input": "boiling point"}])
    world.replies.append("357 apparently")
    await world.send(world.people["anna"], "mitski can u google the boiling point of mercury")
    assert looked and "not looking it up" not in world.prompts[0]


@pytest.mark.parametrize(
    ("line", "servile"),
    [
        ("i will remind him in 2hrs that his game is done", True),
        ("heres a quick recipe for u", True),
        ("ingredients: flour, sugar", True),
        ("hope this helps!", True),
        ("let me know if u need anything", True),
        ("consider it done", True),
        ("i will kill u lol", False),
        ("i will be there at 8", False),
        ("bet ill bug him in 2h", False),
        ("i love lemon drizzle cake", False),
    ],
)
def test_what_counts_as_assistant_speak(line, servile):
    assert bool(SERVILE.search(line)) is servile


def test_list_lines():
    assert [bool(LIST_LINE.match(x)) for x in ("1. flour", "- sugar", "2) eggs", "-_- lol", "lol")] == [
        True,
        True,
        True,
        False,
        False,
    ]
