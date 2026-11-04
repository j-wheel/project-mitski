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


async def test_trivial_messages_skip_planning(world):
    asked = planner(world)
    world.replies.append("hii")
    await world.send(world.people["bob"], "mitski hi")
    assert asked == []
    assert world.sent_text() == ["hii"]
