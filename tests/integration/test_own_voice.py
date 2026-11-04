import time

from mitski.memory.database import PeopleDB


def planner(world, **plan):
    async def ask_json(system, user, schema, max_tokens=400, think=False):
        if "reply_type" not in schema.get("properties", {}):
            return None
        return {"to_her": "her", "wants": "", "reply_type": "answer_question", "answer": "", "tools": [], **plan}

    world.app.cfg.THINKING = True
    world.app.helper.ask_json = ask_json


async def test_a_draft_naming_herself_is_sent_in_first_person(world):
    world.replies.append("mitski is so tired rn")
    await world.send(world.people["anna"], "mitski how are u")
    assert world.sent_text() == ["i'm so tired rn"]
    assert world.app.metrics.done[-1].events["third person fixed"] == 1


async def test_a_speaker_label_with_her_name_is_stripped(world):
    world.replies.append("mitski: heyy")
    await world.send(world.people["anna"], "mitski hi")
    assert world.sent_text() == ["heyy"]


async def test_she_can_still_say_her_own_name(world):
    world.replies.append("call me mitski")
    await world.send(world.people["anna"], "mitski what should i call u")
    assert world.sent_text() == ["call me mitski"]


async def test_answering_about_herself_as_she_is_redone(world):
    world.replies.extend(["she's still here", "ya im still here"])
    await world.send(world.people["anna"], "mitski are u still here")
    assert world.sent_text() == ["ya im still here"]
    assert "say i, me and my" in world.prompts[-1]
    assert world.app.metrics.done[-1].events["redo third person"] == 1


async def test_talking_about_someone_else_as_she_is_fine(world):
    world.replies.append("she's asleep lol")
    await world.send(world.people["anna"], "mitski is she still up")
    assert world.sent_text() == ["she's asleep lol"]
    assert len(world.prompts) == 1


async def test_a_third_person_plan_reaches_her_in_her_own_voice(world):
    planner(world, answer="yes, she's still here", wants="to know if mitski is still here")
    world.replies.append("ya still here")
    await world.send(world.people["anna"], "mitski are u still here?")
    assert "What to tell them: yes, i'm still here" in world.prompts[-1]
    assert "What anna wants: to know if you're still here" in world.prompts[-1]


async def test_a_plan_about_another_woman_keeps_she(world):
    planner(world, answer="she's in lisbon")
    world.replies.append("lisbon")
    await world.send(world.people["anna"], "mitski where did she go?")
    assert "What to tell them: she's in lisbon" in world.prompts[-1]


async def test_the_planner_is_asked_for_her_own_voice(world):
    asked = []

    async def ask_json(system, user, schema, max_tokens=400, think=False):
        asked.append(user)
        return None

    world.app.cfg.THINKING = True
    world.app.helper.ask_json = ask_json
    world.replies.append("ok")
    await world.send(world.people["anna"], "mitski are u still here?")
    assert "third person" not in asked[0]
    assert "she's still here" not in asked[0]
    assert "yes, i'm still here" in asked[0]


def person(**fields):
    return {"name": "bob", "first_seen": 0, "last_seen": time.time(), "talks": 9, "vibe": 0.0, **fields}


async def test_old_memories_are_rewritten_on_load_after_a_backup(world):
    memory = world.app.memory
    memory.people["1"] = memory._migrate(
        person(
            portrait="bob is one of mitski's buddies, he plays cs",
            talk_style="Mitski is playful and she teases him",
            episodes=[{"id": 1, "t": 1, "u": 1, "summary": "he showed mitski a meme", "where": "", "mood": ""}],
            facts=[{"id": 1, "text": "only plays with mitski's group", "cat": "life", "t": 1, "src": "said"}],
        )
    )
    memory.own = {
        "facts": [
            {"id": 1, "text": "is always in her own world", "cat": "life", "t": 1},
            {"id": 2, "text": "insists she is a real person, not an AI", "cat": "life", "t": 1},
            {"id": 3, "text": "is not an AI", "cat": "life", "t": 1},
            {"id": 4, "text": "plays cs with bots", "cat": "games", "t": 1},
        ],
        "next_id": 5,
    }
    memory.dirty = True
    await memory.flush()
    backup = memory.db.path.with_name("memory.before-voice-fix.db")
    assert not backup.exists()

    memory.load()

    d = memory.people["1"]
    assert d["portrait"] == "bob is one of your buddies, he plays cs"
    assert d["talk_style"] == "You're playful and you tease him"
    assert d["episodes"][0]["summary"] == "he showed you a meme"
    assert d["facts"][0]["text"] == "only plays with your group"
    assert [f["text"] for f in memory.own["facts"]] == ["is always in your own world", "plays cs with bots"]
    assert memory.dirty

    assert backup.exists()
    saved_copy, saved_own = PeopleDB(backup).load()
    assert saved_copy["1"]["portrait"] == "bob is one of mitski's buddies, he plays cs"
    assert len(saved_own["facts"]) == 4

    await memory.flush()
    again, own = PeopleDB(memory.db.path).load()
    assert again["1"]["portrait"] == d["portrait"]
    assert len(own["facts"]) == 2


async def test_loading_clean_memories_changes_nothing(world):
    memory = world.app.memory
    memory.people["1"] = memory._migrate(person(portrait="one of your buddies, he plays cs"))
    memory.dirty = True
    await memory.flush()
    memory.load()
    assert not memory.dirty
    assert not memory.db.path.with_name("memory.before-voice-fix.db").exists()


async def test_rewritten_memories_reach_her_prompt_as_you(world):
    memory = world.app.memory
    memory.enabled = True
    world.app.cfg.MEMORY = True
    bob = world.people["bob"]
    memory.people[str(bob.id)] = memory._migrate(person(portrait="Mitski is bob's buddy and he likes her"))
    memory.dirty = True
    await memory.flush()
    memory.load()
    world.replies.append("ok")
    await world.send(bob, "mitski hi")
    assert "You're bob's buddy" in world.prompts[-1]
    assert "Mitski is bob" not in world.prompts[-1]


async def test_a_new_summary_written_in_third_person_is_stored_as_you(world):
    memory = world.app.memory
    d = memory._migrate(person(session_start=0))
    her = world.her
    data = {"conversation": {"summary": "bob teased mitski and he laughed", "mood": ""}}
    memory.apply_json(d, data, ["bob"], her.name, [("them", "hi")], took_part=True)
    memory.fix_voice_of(d)
    assert d["episodes"][-1]["summary"] == "bob teased you and he laughed"
