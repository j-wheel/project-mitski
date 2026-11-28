from mitski.testing.fakes import settle


def thinking(world, answers):
    app = world.app
    app.cfg.INNER_THOUGHTS = True
    app.cfg.THOUGHT_EVERY = 3
    app.cfg.ACTIVE_COOLDOWN = 0
    asked = []

    async def ask_json(system, user, schema, max_tokens=400, think=False):
        if "motivation" not in schema.get("properties", {}):
            return None
        asked.append(user)
        return answers.pop(0) if answers else None

    app.helper.ask_json = ask_json
    app.thoughts.last_at.clear()
    return asked


async def chat(world, lines):
    for name, text in lines:
        await world.send(world.people[name], text, to_her=False)


async def test_she_joins_in_when_she_really_wants_to_and_says_her_thought(world):
    asked = thinking(world, [{"thought": "ok laufey is SO good", "target": 2, "motivation": 5}])
    world.replies.append("LAUFEY IS SO GOOD")
    await chat(world, [("anna", "what are u guys listening to"), ("bob", "laufey lately"), ("anna", "who??")])
    await settle(world.app)
    assert len(asked) == 1 and "[2] bob: laufey lately" in asked[0]
    assert world.sent_text() == ["LAUFEY IS SO GOOD"]
    assert 'You were reading along and thought: "ok laufey is SO good"' in world.prompts[-1]


async def test_a_lukewarm_thought_is_kept_and_she_stays_quiet(world):
    asked = thinking(
        world,
        [
            {"thought": "valorant again lol", "target": 1, "motivation": 3},
            {"thought": "nothing", "target": 0, "motivation": 1},
        ],
    )
    await chat(world, [("anna", "valorant?"), ("bob", "ya"), ("anna", "ok joining")])
    await settle(world.app)
    world.app.thoughts.last_at.clear()
    await chat(world, [("bob", "gg"), ("anna", "gg"), ("bob", "again?")])
    await settle(world.app)
    assert world.sent_text() == []
    assert len(asked) == 2 and "Things she thought earlier but didn't say: valorant again lol" in asked[1]


async def test_she_only_thinks_every_few_messages(world):
    asked = thinking(world, [])
    await chat(world, [("anna", "a"), ("bob", "b")])
    await settle(world.app)
    assert asked == []


async def test_the_old_random_joining_comes_back_when_it_is_off(world):
    asked = thinking(world, [{"thought": "x", "target": 1, "motivation": 5}])
    world.app.cfg.INNER_THOUGHTS = False
    await chat(world, [("anna", "a"), ("bob", "b"), ("anna", "c")])
    await settle(world.app)
    assert asked == [] and world.sent_text() == []
