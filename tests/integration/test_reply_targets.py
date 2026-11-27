from mitski.chat import pipeline, shape
from mitski.chat.sender import Outgoing
from mitski.testing.fakes import settle


def replied_to(message):
    return message.reference.message_id if message.reference else None


def checker(world, verdicts):
    calls = []

    async def ask_json(system, user, schema, max_tokens=400, think=False):
        if "mixed_up" not in (schema or {}).get("properties", {}):
            return None
        calls.append(user)
        to = verdicts.pop(0) if verdicts else 0
        return {"fits": to == 0, "to": to, "mixed_up": False}

    world.app.cfg.ADDRESSEE_CHECK = True
    world.app.helper.ask_json = ask_json
    return calls


async def test_a_reply_that_fits_someone_elses_message_never_goes_to_them(world):
    anna, bob = world.people["anna"], world.people["bob"]
    keys = world.say(bob, "has anyone seen my keys", to_her=False)
    await world.app.router.route(keys)
    checker(world, [1, 1])
    world.replies += ["theyre on the kitchen table", "check by the door", "class was fine, kinda long"]
    question = await world.send(anna, "mitski how was class")
    await settle(world.app)
    sent = world.client.sent
    assert all(replied_to(m) != keys.id for m in sent)
    assert all(f"<@{bob.id}>" not in m.content for m in sent)
    assert [m.content for m in sent] == ["class was fine, kinda long"]
    assert replied_to(sent[0]) in (None, question.id)


async def test_joining_in_it_goes_out_replying_to_nobody(world):
    anna, bob = world.people["anna"], world.people["bob"]
    first = world.say(bob, "who won the game last night", to_her=False)
    await world.app.router.route(first)
    second = world.say(anna, "im so tired today", to_her=False)
    await world.app.router.route(second)

    async def the_other_one(system, user, schema, max_tokens=400, think=False):
        if "mixed_up" not in (schema or {}).get("properties", {}):
            return None
        meant = int(user.split("is replying to [")[1].split("]")[0])
        return {"fits": False, "to": 3 - meant, "mixed_up": False}

    world.app.cfg.ADDRESSEE_CHECK = True
    world.app.helper.ask_json = the_other_one
    world.replies.append("the blue team won i think")
    world.app.pipeline.join_in(world.channel, second)
    await settle(world.app)
    [sent] = world.client.sent
    assert replied_to(sent) is None and "<@" not in sent.content


async def test_the_sender_refuses_to_reply_to_a_message_the_reply_isnt_for(world):
    anna, bob = world.people["anna"], world.people["bob"]
    theirs = world.say(bob, "hey", to_her=False)
    mine = world.say(anna, "mitski hi")
    sent = await world.app.sender.send(world.channel, ["hiii"], reply_to=theirs, owned={mine.id: anna.id}, job=7)
    assert replied_to(sent[0]) is None


async def test_the_sender_refuses_to_ping_someone_the_reply_isnt_for(world):
    anna, bob = world.people["anna"], world.people["bob"]
    mine = world.say(anna, "mitski hi")
    going = Outgoing(world.channel, None, None, bob, False, False, True, owned={mine.id: anna.id}, job=3)
    assert going.with_ping("yo", True) == "yo"
    going = Outgoing(world.channel, None, None, anna, False, False, True, owned={mine.id: anna.id}, job=3)
    assert going.with_ping("yo", True) == f"<@{anna.id}> yo"


async def test_its_own_message_is_fine(world):
    anna = world.people["anna"]
    mine = world.say(anna, "mitski hi")
    sent = await world.app.sender.send(world.channel, ["hiii"], reply_to=mine, owned={mine.id: anna.id})
    assert replied_to(sent[0]) == mine.id


async def test_every_reply_gets_its_own_number(world):
    seen = []
    real = pipeline.ReplyPipeline._deliver

    async def watch(self, reply):
        seen.append((reply.job, set(reply.owned)))
        return await real(self, reply)

    pipeline.ReplyPipeline._deliver = watch
    try:
        world.replies += ["hii", "yo"]
        one = await world.send(world.people["anna"], "mitski hey")
        two = await world.send(world.people["bob"], "mitski sup")
    finally:
        pipeline.ReplyPipeline._deliver = real
    (job1, owned1), (job2, owned2) = seen
    assert job2 > job1 and one.id in owned1 and two.id in owned2 and one.id not in owned2


def test_a_long_burst_of_one_liners_becomes_a_few_messages():
    lines = ["ya", "same", "lol", "wait", "fr", "no way", "omg", "ok"]
    out = shape.bubbles(lines)
    assert len(out) == shape.QUICK_MAX
    assert "\n".join(out).split("\n") == lines


def test_stickers_stay_their_own_message():
    out = shape.bubbles(["ya", "[sticker: cat]", "lol", "ok", "fr", "same"], limit=3)
    assert "[sticker: cat]" in out


def test_blank_lines_only_in_a_proper_long_message():
    long_one = ["x" * 90]
    assert shape.paragraphs([long_one, long_one], longer=True)
    assert not shape.paragraphs([long_one, long_one], longer=False)
    assert not shape.paragraphs([["ya"], long_one], longer=True)


async def test_a_quick_reply_isnt_eight_messages_in_a_row(world, monkeypatch):
    monkeypatch.setattr(shape, "pick", lambda *a, **k: shape.QUICK)
    world.replies.append("ya\nsame\nlol\nwait\nfr\nno way\nomg\nok")
    await world.send(world.people["anna"], "mitski hey")
    assert len(world.client.sent) == shape.QUICK_MAX


async def test_no_reply_to_each_message_when_nobody_else_is_talking(world, monkeypatch):
    seen = {}

    def pick(answers, **kw):
        seen.update(kw)
        return shape.QUICK

    monkeypatch.setattr(shape, "pick", pick)

    async def owners(lines, things):
        return [t.msg for t in things][: len(lines)]

    monkeypatch.setattr(world.app.review, "match_answers", owners)
    anna = world.people["anna"]
    first = world.say(anna, "mitski what game are u playing")
    await world.app.router.route(first)
    await world.app.router.route(world.say(anna, "and where do u live?", to_her=False))
    world.replies.append("cs2\nportugal")
    await settle(world.app)
    assert seen and seen["can_thread"] is False
