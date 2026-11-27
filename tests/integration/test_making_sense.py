from mitski.testing.fakes import FakeMessage, settle


def planner(world, **plan):
    asked = []

    async def ask_json(system, user, schema, max_tokens=400, think=False):
        if "reply_type" not in schema.get("properties", {}):
            return None
        asked.append(user)
        base = {
            "to_her": "her",
            "situation": "",
            "wants": "",
            "mood": "neutral",
            "subtext": "",
            "move": "",
            "follow_up": "",
        }
        return {**base, "reply_type": "small_talk", "answer": "", "tools": [], "length": "short", "ask": "none", **plan}

    world.app.cfg.THINKING = True
    world.app.helper.ask_json = ask_json
    return asked


async def test_she_connects_the_dots_before_replying(world):
    wheel, rat = world.person("wheel"), world.person("ratking")
    world.replies.append("omg i just realized my friend is in the kitchen")
    mine = await world.send(rat, "mitski whats up")
    hers = world.client.sent[-1]
    await world.app.router.route(
        FakeMessage(world.channel, wheel, "just checked if u steal my red velvet cake", reference=hers)
    )
    asked = planner(
        world,
        situation="wheel is the friend in your kitchen, he was checking if you stole his cake, and ratking is asking what he's making",
        answer="idk ask wheel lol hes the one in there",
        reply_type="answer_question",
    )
    world.replies.append("idk ask wheel lol hes in there")
    await world.send(rat, "mitski what they makin?", reference=hers)
    assert mine is not None
    assert "Connect the dots" in asked[-1] and "wheel" in asked[-1]
    prompt = world.prompts[-1]
    assert "What's going on: wheel is the friend in your kitchen" in prompt
    assert world.sent_text()[-1] == "idk ask wheel lol hes in there"


async def test_she_doesnt_say_the_same_thing_again(world):
    world.replies.append("yeah i know :)")
    await world.send(world.people["anna"], "mitski ur so good at this game")
    world.replies += ["yeahhh i know,,", "stoppp ur gonna make me blush"]
    await world.send(world.people["anna"], "mitski no fr ur cracked")
    assert world.sent_text() == ["yeah i know :)", "stoppp ur gonna make me blush"]
    assert "You just said pretty much that already" in world.prompts[-1]


async def test_no_laughing_at_nothing(world):
    world.replies += ["AHAHAHAHAHAHAA", "wait thats so sad, u ok?"]
    await world.send(world.people["anna"], "mitski my cat ran away today")
    assert world.sent_text() == ["wait thats so sad, u ok?"]


async def test_laughing_at_something_funny_is_fine(world):
    world.replies.append("AHAHAHAHAHAHAHA")
    await world.send(world.people["anna"], "mitski i walked into a glass door in front of everyone 😭")
    assert world.sent_text() == ["AHAHAHA"]


async def test_the_planner_is_asked_whats_going_on(world):
    asked = planner(world)
    world.replies.append("ya")
    await world.send(world.people["anna"], "mitski did u see what sam said earlier")
    await settle(world.app)
    assert "situation:" in asked[0]
