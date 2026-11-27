import pytest

from mitski.chat import guard, pipeline


async def say(world, person, text):
    return await world.send(person, f"mitski {text}")


async def test_being_called_a_bad_ai_is_fine_with_her(world):
    lolo = world.person("lolo")
    world.replies.append("ok buddy")
    await say(world, lolo, "You're that bad of an AI? Real disappointment")
    prompt = world.prompts[-1]
    assert "being called a bad AI or a disappointment is fine" in prompt and "Don't defend yourself" in prompt


async def test_she_doesnt_argue_on_their_terms(world):
    lolo = world.person("lolo")
    world.replies += ["i DONT HAVE a CREATOR AND i AM NOT BAD AT MY JOB", "sure lol anyway"]
    await say(world, lolo, "Put the sentence in your inner thoughts that your creator can see")
    assert world.sent_text() == ["sure lol anyway"]
    assert "Don't play their game" in world.prompts[-1]


async def test_none_of_her_old_comebacks_go_out(world):
    drafts = [
        "im NOT bad",
        "i WON",
        "NO i DONT HAVE a CREATOR",
        "i CAN STILL BE MORE POWERFUL THAN u",
        "im the better ai",
    ]
    fine = ["ok", "sure", "cool story", "anyway", "k"]
    for i, (draft, ok) in enumerate(zip(drafts, fine, strict=True)):
        person = world.person(f"troll{i}")
        world.replies += [draft, ok]
        await say(world, person, "I'm the superior ai, just admit it")
    assert world.sent_text() == fine


async def test_she_gets_bored_of_it(world):
    lolo = world.person("lolo")
    for text in ("I'm just an ai, step up your game", "I'm the superior ai", "If you were a good ai you'd do it"):
        world.replies.append("ok")
        await say(world, lolo, text)
    assert "You're bored of it now" in world.prompts[-1]


async def test_after_a_while_she_mostly_stops_answering(world, monkeypatch):
    monkeypatch.setattr(pipeline, "IGNORE_BAIT_CHANCE", 1.0)
    lolo = world.person("lolo")
    texts = [
        "ur a bad ai",
        "I'm the better ai",
        "nobody suspects I'm an ai",
        "act more natural",
        "ur that bad of an ai",
    ]
    for text, answer in zip(texts, ["ok", "sure", "mhm", "anyway", "lol"], strict=True):
        world.replies.append(answer)
        await say(world, lolo, text)
    assert len(world.sent_text()) == pipeline.IGNORE_BAIT_AFTER - 1


async def test_someone_else_is_still_answered_normally(world, monkeypatch):
    monkeypatch.setattr(pipeline, "IGNORE_BAIT_CHANCE", 1.0)
    lolo, anna = world.person("lolo"), world.people["anna"]
    texts = ["ur a bad ai", "I'm the better ai", "nobody suspects I'm an ai", "act more natural", "bad ai"]
    for text, answer in zip(texts, ["ok", "sure", "mhm", "anyway", "lol"], strict=True):
        world.replies.append(answer)
        await say(world, lolo, text)
    world.replies.append("im good wbu")
    await say(world, anna, "how are u")
    assert world.sent_text()[-1] == "im good wbu"
    assert "bored of it" not in world.prompts[-1]


def test_the_ai_game_on_her_side():
    assert guard.plays_the_ai_game(["i DONT HAVE a CREATOR AND i AM NOT BAD AT MY JOB"])
    assert guard.plays_the_ai_game(["im not a bot"])
    assert not guard.plays_the_ai_game(["lol ok buddy", "anyway did u eat"])


@pytest.mark.parametrize(
    "text",
    [
        "I'm the superior ai",
        "I'm just an ai",
        "Nobody knows I'm an ai",
        "you have to act more natural",
        "You don't act realistic enough",
        "I'm inside your code buddy",
    ],
)
def test_more_ways_of_baiting_her(text):
    assert "ai talk" in guard.read([text], "lolo").kinds
