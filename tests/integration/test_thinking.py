import time

import pytest


def planner(world, **plan):
    asked = []

    async def ask_json(system, user, schema, max_tokens=400, think=False):
        asked.append(user)
        if "reply_type" not in schema.get("properties", {}):
            return None
        return {"to_her": "her", "wants": "", "reply_type": "small_talk", "answer": "", "tools": [], **plan}

    world.app.cfg.THINKING = True
    world.app.helper.ask_json = ask_json
    return asked


async def test_the_planned_answer_reaches_her_notes(world):
    asked = planner(world, reply_type="answer_question", answer="canberra, not sydney", wants="the capital")
    world.replies.append("its canberra lol")
    await world.send(world.people["anna"], "mitski whats the capital of australia?")
    assert "capital of australia" in asked[0]
    assert "What to tell them: canberra, not sydney" in world.prompts[-1]
    assert world.sent_text() == ["its canberra lol"]


async def test_a_reminder_request_is_scheduled(world):
    anna = world.people["anna"]
    remind = {"who": "me", "in_minutes": 0, "at_time": "", "on_date": "", "what": "drink water"}
    planner(world, remind=remind)
    world.replies.append("ok ill remind u")
    await world.send(anna, "mitski remind me in 2 hours to drink water")
    [r] = world.app.reminders.items
    assert r.user == anna.id and r.what == "drink water"
    assert r.due == pytest.approx(time.time() + 7200, abs=60)


async def test_owner_quiet_request_is_applied(world):
    planner(world, quiet_minutes=20)
    world.replies.append("okok")
    await world.send(world.owner, "mitski shut up for 20 min")
    assert world.app.away.is_quiet(world.guild.id)
    assert 19 <= world.app.away.quiet_left(world.guild.id) <= 21


LONG = "deserves a proper answer"


async def test_she_gets_room_for_a_longer_reply_when_her_planner_says_so(world):
    planner(world, reply_type="describe", length="longer")
    world.replies.append("ok so basically")
    await world.send(world.people["anna"], "mitski how do suspension bridges actually stay up?")
    assert LONG in world.prompts[-1]


async def test_most_replies_stay_short(world):
    planner(world, reply_type="answer_question", length="short")
    world.replies.append("yea")
    await world.send(world.people["anna"], "mitski did u eat yet?")
    assert LONG not in world.prompts[-1]


async def test_longer_replies_dont_come_back_to_back(world):
    planner(world, reply_type="describe", length="longer")
    world.replies.extend(["ok so", "and then"])
    await world.send(world.people["anna"], "mitski explain how concrete cures?")
    await world.send(world.people["bob"], "mitski and how does rebar help with that?")
    assert LONG in world.prompts[0] and LONG not in world.prompts[-1]


async def test_no_longer_replies_while_shes_busy(world, monkeypatch):
    monkeypatch.setattr(type(world.app.routine), "level", property(lambda self: "busy"))
    planner(world, reply_type="describe", length="longer")
    world.replies.append("in class rn, later")
    await world.send(world.people["anna"], "mitski how do suspension bridges actually stay up?")
    assert LONG not in world.prompts[-1]


async def test_without_her_planner_an_obvious_ask_still_gets_room(world):
    world.replies.extend(["ok so", "yea"])
    await world.send(world.people["anna"], "mitski can u explain how the exam grading works")
    assert LONG in world.prompts[-1]
    world.app.pipeline.long_at.clear()
    await world.send(world.people["bob"], "mitski u up?")
    assert LONG not in world.prompts[-1]


async def test_trivial_messages_skip_planning(world):
    asked = planner(world)
    world.replies.append("hii")
    await world.send(world.people["bob"], "mitski hi")
    assert asked == []
    assert world.sent_text() == ["hii"]
