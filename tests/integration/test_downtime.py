import json
import time

from mitski.llm.helper import Answer
from mitski.social.routine import Routine

NOTES = {
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
    "feelings": [],
}
REFLECTED = {
    "portrait": "an old friend from the server who never shuts up about laufey",
    "talk_style": "",
    "inside_jokes": [],
    "avoid": [],
    "shared": [],
    "merge": [],
    "forget": [],
    "history": "",
}


def resting(world, on=True):
    downtime = world.app.downtime
    world.app.cfg.DOWNTIME = True
    if on:
        world.app.gpu.last_busy = 0.0
        downtime.started = time.monotonic() - 3600
    else:
        world.app.gpu.last_busy = time.monotonic()
    return downtime


def helper_answers(world):
    asked = []

    async def ask(system, user_text, schema=None, max_tokens=700, think=False):
        reflecting = "portrait" in (schema or {}).get("properties", {})
        asked.append("reflect" if reflecting else "notes")
        return Answer(json.dumps(REFLECTED if reflecting else NOTES))

    world.app.helper.ask = ask
    return asked


async def someone_worth_rethinking(world, facts=4):
    world.app.cfg.MEMORY = True
    world.app.memory.enabled = True
    anna = world.people["anna"]
    world.replies.append("ya")
    await world.send(anna, "mitski have u heard the new laufey album")
    d = world.app.memory.get(anna.id)
    d["facts"] = [{"id": i, "text": f"likes laufey song {i}", "cat": "music", "t": 0} for i in range(1, facts + 1)]
    d["since_reflect"] = 5
    d["since_notes"] = 1
    return anna, d


async def test_rethinking_someone_waits_for_downtime(world):
    resting(world, on=False)
    asked = helper_answers(world)
    anna, d = await someone_worth_rethinking(world)
    world.app.memory.running.add(anna.id)
    await world.app.memory.update(anna, world.channel)
    assert "reflect" not in asked and not d.get("portrait")
    assert f"reflect-{anna.id}" in world.app.downtime.waiting

    await world.app.downtime.tick()
    assert "reflect" not in asked

    resting(world)
    await world.app.downtime.tick()
    assert asked[-1] == "reflect" and d["portrait"] == REFLECTED["portrait"]
    assert world.app.downtime.waiting == {} and world.app.downtime.done == 1


async def test_a_nearly_full_memory_is_still_rethought_right_away(world):
    resting(world, on=False)
    asked = helper_answers(world)
    anna, d = await someone_worth_rethinking(world, facts=world.app.memory.facts_max)
    world.app.memory.running.add(anna.id)
    await world.app.memory.update(anna, world.channel)
    assert "reflect" in asked and d["portrait"] == REFLECTED["portrait"]
    assert world.app.downtime.waiting == {}


async def test_with_downtime_off_it_runs_right_away(world):
    asked = helper_answers(world)
    anna, d = await someone_worth_rethinking(world)
    world.app.memory.running.add(anna.id)
    await world.app.memory.update(anna, world.channel)
    assert "reflect" in asked and d["portrait"] == REFLECTED["portrait"]


async def test_she_rests_while_asleep_in_her_routine(world, monkeypatch):
    downtime = resting(world, on=False)
    assert downtime.resting() == ""
    monkeypatch.setattr(Routine, "level", property(lambda self: "asleep"))
    assert downtime.resting() == "asleep"


async def test_saved_work_runs_anyway_after_waiting_too_long(world):
    downtime = resting(world, on=False)
    ran = []

    async def job():
        ran.append(1)

    downtime.later("job", job, "a job")
    await downtime.tick()
    assert ran == []
    since, make, what = downtime.waiting["job"]
    downtime.waiting["job"] = (since - 13 * 3600, make, what)
    await downtime.tick()
    assert ran == [1] and downtime.overdue == 1
    assert "ran anyway" in downtime.report()


async def test_the_same_job_is_only_saved_once_and_oldest_goes_first(world):
    downtime = resting(world, on=False)
    ran = []

    def job(n):
        async def go():
            ran.append(n)

        return go

    downtime.later("a", job("a"), "a")
    downtime.later("b", job("b"), "b")
    downtime.later("a", job("a again"), "a")
    resting(world)
    await downtime.tick()
    await downtime.tick()
    assert ran == ["a", "b"]


async def test_look_ups_wait_for_downtime(world):
    resting(world, on=False)
    world.app.cfg.LOOK_UP_INTERESTS = True
    world.app.search.provider = "ddg"
    looked = []

    async def learn(topic, name=""):
        looked.append(topic)

    world.app.knowledge.learn = learn
    world.app.knowledge.want(["laufey (singer)"], "anna")
    assert looked == [] and len(world.app.downtime.waiting) == 1
    resting(world)
    await world.app.downtime.tick()
    assert looked == ["laufey (singer)"]
