import re
from types import SimpleNamespace as NS


def system_part(prompt):
    m = re.search(r"<\|im_start\|>system\n(.*?)<\|im_end\|>", prompt, re.S)
    return m.group(1) if m else ""


async def test_each_conversation_keeps_its_own_slot_and_helpers_keep_theirs(world):
    llm = world.app.llm
    llm.info.slots = 3
    assert llm.slot_for(True) == 2
    assert llm.slot_for(False, "general") == 0
    assert llm.slot_for(False, "dm-anna") == 1
    assert llm.slot_for(False, "general") == 0
    assert llm.slot_for(False, "dm-bob") == 1
    assert llm.slot_for(False, "general") == 0
    assert llm.slot_for(False, "dm-anna") == 1
    llm.info.slots = 2
    assert (llm.slot_for(False, "x"), llm.slot_for(True)) == (0, 1)
    llm.info.slots = 1
    assert llm.slot_for(False, "x") is None


async def test_the_history_window_keeps_its_start_until_it_grows_too_long(world):
    ctx = world.app.context
    world.app.cfg.CONTEXT_MSGS = 4
    msgs = [NS(id=i) for i in range(1, 30)]
    first = ctx.sticky("c", msgs[:6])
    assert [m.id for m in first] == [3, 4, 5, 6]
    grown = ctx.sticky("c", msgs[:12])
    assert grown[0].id == 3 and grown[-1].id == 12
    jumped = ctx.sticky("c", msgs[:20])
    assert [m.id for m in jumped] == [17, 18, 19, 20]


async def test_her_system_prompt_stays_the_same_for_different_people(world):
    world.app.memory.blurb = lambda user, full=True, context="": f"You remember things about {user.name}."
    world.replies.extend(["hey anna", "hey bob"])
    await world.send(world.people["anna"], "mitski hi")
    await world.send(world.people["bob"], "mitski yo")
    a, b = world.prompts[-2], world.prompts[-1]
    assert system_part(a) and system_part(a) == system_part(b)
    assert "You remember things about anna." not in system_part(a)
    assert "You remember things about anna." in a and "You remember things about bob." in b


async def test_cache_numbers_show_up_in_stats(world):
    llm = world.app.llm
    llm._note_cache({"timings": {"prompt_n": 120, "cache_n": 2880}}, helper=False)
    llm._note_cache({"timings": {"prompt_n": 999, "cache_n": 0}}, helper=True)
    assert llm.cache_report().startswith("prompt cache: 96% of her reply prompts came from cache over 1 replies")
