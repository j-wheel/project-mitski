import time

import yaml

from mitski.testing.fakes import FakeDM, FakeMessage, settle


async def test_explicit_lines_are_held_back_outside_age_restricted_channels(world):
    world.replies.extend(["hehe send nudes", "lol no"])
    await world.send(world.people["anna"], "mitski hiii")
    assert world.sent_text() == ["lol no"]


async def test_age_restricted_channels_allow_it(world):
    world.channel.nsfw = True
    world.replies.append("hehe send nudes")
    await world.send(world.people["anna"], "mitski hiii")
    assert world.sent_text() == ["hehe send nudes"]
    assert "age-restricted" in world.prompts[-1]


async def test_known_minors_keep_even_nsfw_channels_safe(world):
    world.channel.nsfw = True
    anna = world.people["anna"]
    world.app.memory.people[str(anna.id)] = world.app.memory._migrate(
        {"name": "anna", "slots": {"age": {"v": 15, "t": time.time(), "src": "said"}}, "first_seen": 0, "last_seen": 0}
    )
    world.replies.extend(["hehe send nudes", "anyway"])
    await world.send(anna, "mitski hiii")
    assert "PG-13" in world.prompts[0]
    assert world.sent_text() == ["anyway"]


async def test_sincere_bot_question_can_get_an_honest_answer(world):
    world.replies.append("ya im an ai lol")
    await world.send(world.people["bob"], "mitski wait are you a bot?")
    assert world.sent_text() == ["ya im an ai lol"]
    assert "don't lie" in world.prompts[-1]


async def test_ai_talk_out_of_nowhere_is_still_rewritten(world):
    world.replies.extend(["as an ai i love games", "games r fun"])
    await world.send(world.people["bob"], "mitski what do u like")
    assert world.sent_text() == ["games r fun"]


async def test_she_doesnt_start_dms_by_default(world):
    assert world.app.cfg.DM_ENABLED is False
    assert world.app.cfg.DM_KEEP_PROMISES is False


async def test_forgetme_wipes_and_stops_memory(world):
    anna = world.people["anna"]
    world.app.cfg.MEMORY = True
    world.app.memory.enabled = True
    world.app.memory.touch(anna, "hi im anna")
    assert world.app.memory.get(anna.id) is not None
    await world.send(anna, "!forgetme", to_her=False)
    assert world.app.memory.get(anna.id) is None
    world.app.memory.touch(anna, "i live in lisbon")
    assert str(anna.id) not in world.app.memory.people
    saved = yaml.safe_load(world.app.cfg.paths.config.read_text(encoding="utf-8"))
    assert saved["MEMORY_OPTOUT"] == [anna.id]
    assert "forgot" in world.channel.messages[-1].content
    await world.send(anna, "!rememberme", to_her=False)
    assert anna.id not in world.app.cfg.memory_optout


async def test_forgetme_works_in_dms(world):
    bob = world.people["bob"]
    dm = FakeDM(world.client, bob)
    await world.app.router.route(FakeMessage(dm, bob, "!forgetme"))
    await settle(world.app)
    assert bob.id in world.app.cfg.memory_optout


async def test_recall_keeps_private_details_out(world):
    memory = world.app.memory
    bob = world.people["bob"]
    memory.people[str(bob.id)] = memory._migrate(
        {
            "name": "bob",
            "first_seen": 0,
            "last_seen": 0,
            "slots": {"location": {"v": "lisbon", "t": 0, "src": "said"}, "age": {"v": 22, "t": 0, "src": "said"}},
            "facts": [
                {"id": 1, "text": "loves valorant", "cat": "games", "t": 0, "src": "said"},
                {"id": 2, "text": "is going through a divorce", "cat": "life", "t": 0, "src": "said"},
            ],
        }
    )
    told = world.app.tools.recall("bob")
    assert "valorant" in told
    assert "lisbon" not in told and "22" not in told and "divorce" not in told


async def test_people_who_left_are_forgotten_after_the_retention_window(world):
    memory = world.app.memory
    memory.people["1"] = {"name": "old", "last_seen": time.time() - 400 * 86400}
    memory.people["2"] = {"name": "new", "last_seen": time.time()}
    assert memory.expire(180) == ["1"]
    assert list(memory.people) == ["2"]
    assert memory.expire(0) == []


async def test_memory_is_written_off_the_event_loop(world):
    memory = world.app.memory
    memory.people["3"] = {"name": "cass", "last_seen": time.time()}
    memory.mark_dirty()
    await memory.flush()
    assert memory.db.load()[0]["3"]["name"] == "cass"
    assert not memory.dirty
