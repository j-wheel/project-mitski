import json


def logged(world):
    path = world.app.preferences.path
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def test_a_redo_that_passes_is_kept_as_a_pair(world):
    world.replies.extend(["she's still here", "ya im still here"])
    await world.send(world.people["anna"], "mitski are u still here")
    [pair] = logged(world)
    assert pair["kind"] == "third person" and pair["source"] == "her"
    assert pair["rejected"] == "she's still here" and pair["chosen"] == "ya im still here"
    assert pair["turns"][-1][0] == "user" and "are u still here" in pair["turns"][-1][1]
    assert pair["system"]


async def test_a_redo_that_fails_again_keeps_nothing(world):
    world.replies.extend(["she's still here", "she's still here lol"])
    await world.send(world.people["anna"], "mitski are u still here")
    assert logged(world) == []


async def test_a_reply_that_was_fine_keeps_nothing(world):
    world.replies.append("ya im here")
    await world.send(world.people["anna"], "mitski are u still here")
    assert logged(world) == []


async def test_nothing_is_kept_with_minors_around(world):
    anna = world.people["anna"]
    world.app.ages.is_minor = lambda user: user is anna
    world.replies.extend(["she's still here", "ya im still here"])
    await world.send(anna, "mitski are u still here")
    assert logged(world) == []


async def test_nothing_is_kept_from_people_who_opted_out(world):
    bob = world.people["bob"]
    world.app.cfg.memory_optout.add(bob.id)
    await world.send(bob, "lol", to_her=False)
    world.replies.extend(["she's still here", "ya im still here"])
    await world.send(world.people["anna"], "mitski are u still here")
    assert logged(world) == []


async def test_a_redo_the_safety_check_accepts_is_kept(world, monkeypatch):
    world.app.cfg.SAFETY_REVIEW = True
    verdicts = [{"ok": False}, {"ok": True}]

    async def ask_json(system, user, schema, *args, **kwargs):
        return verdicts.pop(0) if "ok" in schema["properties"] and len(schema["properties"]) == 1 else None

    monkeypatch.setattr(world.app.helper, "ask_json", ask_json)
    world.replies += ["seems fine to the word list", "actually fine"]
    await world.send(world.people["anna"], "mitski hey")
    [pair] = logged(world)
    assert pair["kind"] == "not safe" and pair["chosen"] == "actually fine"


async def test_it_can_be_turned_off(world):
    world.app.cfg.PREFERENCE_LOG = False
    world.replies.extend(["she's still here", "ya im still here"])
    await world.send(world.people["anna"], "mitski are u still here")
    assert logged(world) == []
