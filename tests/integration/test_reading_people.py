import logging


def planner(world, **plan):
    asked = []

    async def ask_json(system, user, schema, max_tokens=400, think=False):
        if "reply_type" not in schema.get("properties", {}):
            return None
        asked.append((user, schema))
        base = {"to_her": "her", "wants": "", "mood": "neutral", "subtext": "", "move": "", "follow_up": ""}
        return {**base, "reply_type": "small_talk", "answer": "", "tools": [], **plan}

    world.app.cfg.THINKING = True
    world.app.helper.ask_json = ask_json
    return asked


async def test_how_she_reads_them_reaches_her_notes(world):
    planner(
        world,
        wants="to share good news and have you hype it",
        mood="excited",
        subtext="they're proud and want it noticed",
        move="hype it up, then ask what grade they got",
        follow_up="wait what did u get on it??",
    )
    world.replies.append("NO WAY congrats!!")
    await world.send(world.people["anna"], "mitski I PASSED MY EXAM")
    prompt = world.prompts[-1]
    assert "What anna wants: to share good news and have you hype it." in prompt
    assert "anna seems excited right now." in prompt
    assert "Under the surface: they're proud and want it noticed." in prompt
    assert "What you're going for: hype it up, then ask what grade they got." in prompt
    assert "you could ask them: wait what did u get on it??" in prompt


async def test_nothing_extra_when_theres_nothing_to_read(world):
    planner(world)
    world.replies.append("lol ya")
    await world.send(world.people["anna"], "mitski this game is so dumb sometimes")
    prompt = world.prompts[-1]
    assert "seems neutral" not in prompt and "Under the surface" not in prompt and "going for" not in prompt


async def test_the_planner_is_asked_for_all_of_it(world):
    asked = planner(world)
    world.replies.append("hm")
    await world.send(world.people["anna"], "mitski do u think i should quit my job")
    user, schema = asked[0]
    for field in ("wants", "mood", "subtext", "move", "follow_up"):
        assert field in schema["required"]
    assert "Read anna the way a friend who knows them would" in user


async def test_she_reads_them_with_what_she_remembers(world):
    world.app.cfg.MEMORY = True
    world.app.memory.enabled = True
    anna = world.people["anna"]
    world.app.memory.touch(anna, "hi")
    d = world.app.memory.get(anna.id)
    d["facts"].append({"id": 1, "text": "has a big exam on friday", "cat": "plans", "t": 0, "tags": ["exam"]})
    asked = planner(world)
    world.replies.append("u got this")
    await world.send(anna, "mitski im so nervous about friday")
    assert "has a big exam on friday" in asked[0][0]


async def test_a_brush_off_drops_the_plan_for_the_reply(world):
    planner(world, ask="effort", move="write out the whole recipe step by step", follow_up="want the frosting too?")
    world.app.cfg.BRUSH_OFF_CHANCE = 1.0
    world.replies.append("just google it lol")
    await world.send(world.people["anna"], "mitski give me a full cake recipe")
    prompt = world.prompts[-1]
    assert "whole recipe step by step" not in prompt and "frosting" not in prompt


class Lines(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


async def test_the_log_line_has_no_empty_bits(world):
    planner(world, wants="to know if you're around", mood="bored")
    world.replies.append("ya im here")
    brain = planner_log()
    seen = Lines()
    brain.addHandler(seen)
    level = brain.level
    brain.setLevel(logging.INFO)
    try:
        await world.send(world.people["anna"], "mitski are u around later tonight or are u busy")
    finally:
        brain.removeHandler(seen)
        brain.setLevel(level)
    line = next(text for text in seen.lines if "wants:" in text)
    assert "|  |" not in line and "small_talk, to her, bored | wants: to know if you're around" in line


def planner_log():
    from mitski.core import logs

    return logs.get("brain")
