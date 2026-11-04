import pytest

from mitski.chat import pipeline, shape
from mitski.testing.fakes import settle


@pytest.fixture
def always_lets_go(monkeypatch):
    monkeypatch.setattr(pipeline, "LET_GO_CHANCE", 1.0)


@pytest.fixture
def layout(monkeypatch):
    def use(kind):
        monkeypatch.setattr(shape, "pick", lambda *a, **k: kind)

    return use


async def burst(world, person, *texts):
    msgs = [world.say(person, texts[0])]
    await world.app.router.route(msgs[0])
    for text in texts[1:]:
        msgs.append(world.say(person, text, to_her=False))
        await world.app.router.route(msgs[-1])
    await settle(world.app)
    return msgs


def replied_to(message):
    return message.reference.message_id if message.reference else None


# tiny follow-ups


async def test_a_closing_lol_is_let_go(world, always_lets_go):
    anna = world.people["anna"]
    world.replies.append("cats are the best")
    await world.send(anna, "mitski cats or dogs")
    world.replies.append("should not be sent")
    await world.send(anna, "lol", to_her=False)
    assert world.sent_text() == ["cats are the best"]
    assert world.app.metrics.done[-1].outcome == "no reply needed"
    assert world.app.addressing.is_engaged(world.channel.id, anna.id)


async def test_a_discord_reply_that_only_pings_her_is_let_go_too(world, always_lets_go):
    anna = world.people["anna"]
    world.replies.append("cats are the best")
    await world.send(anna, "mitski cats or dogs")
    world.replies.append("should not be sent")
    await world.send(anna, "lol", reference=world.client.sent[-1])
    assert world.sent_text() == ["cats are the best"]


async def test_answering_her_question_gets_a_reply(world, always_lets_go):
    anna = world.people["anna"]
    world.replies.append("do u like cats")
    await world.send(anna, "mitski hi")
    world.replies.append("same honestly")
    await world.send(anna, "yes", to_her=False)
    assert world.sent_text() == ["do u like cats", "same honestly"]


async def test_actually_pinging_her_gets_a_reply(world, always_lets_go):
    anna = world.people["anna"]
    world.replies.append("cats are the best")
    await world.send(anna, "mitski cats or dogs")
    world.replies.append("what")
    await world.send(anna, f"<@{world.her.id}> lol")
    assert world.sent_text() == ["cats are the best", "what"]


async def test_goodnight_gets_a_reply(world, always_lets_go):
    anna = world.people["anna"]
    world.replies.append("sleep well then")
    await world.send(anna, "mitski im going to bed")
    world.replies.append("gn")
    await world.send(anna, "gn", to_her=False)
    assert world.sent_text() == ["sleep well then", "gn"]


async def test_the_owner_is_never_let_go(world, always_lets_go):
    world.replies.append("cats are the best")
    await world.send(world.owner, "mitski cats or dogs")
    world.replies.append("lmao")
    await world.send(world.owner, "lol", to_her=False)
    assert world.sent_text() == ["cats are the best", "lmao"]


async def test_the_planner_saying_no_reply_is_believed(world, always_lets_go):
    anna = world.people["anna"]
    world.replies.append("have fun")
    await world.send(anna, "mitski im heading out")

    async def ask_json(system, user, schema, max_tokens=400, think=False):
        return {"to_her": "her", "wants": "", "reply_type": "no_reply", "answer": "", "tools": []}

    world.app.cfg.THINKING = True
    world.app.cfg.THINK_ALWAYS = True
    world.app.helper.ask_json = ask_json
    world.replies.append("should not be sent")
    await world.send(anna, "anyway the bus is finally here so i should go", to_her=False)
    assert world.sent_text() == ["have fun"]


async def test_joining_in_by_herself_still_works_when_nothing_needs_an_answer(world, always_lets_go):
    async def ask_json(system, user, schema, max_tokens=400, think=False):
        return {"to_her": "everyone", "wants": "", "reply_type": "no_reply", "answer": "", "tools": []}

    world.app.cfg.THINKING = True
    world.app.helper.ask_json = ask_json
    world.replies.append("wait i wanna know too")
    msg = world.say(world.people["anna"], "who won the game?", to_her=False)
    world.app.pipeline.join_in(world.channel, msg)
    await settle(world.app)
    assert world.sent_text() == ["wait i wanna know too"]


# one thing, a few lines


async def test_quick_messages_reply_with_the_first_line_only(world, layout):
    layout(shape.QUICK)
    anna = world.people["anna"]
    world.replies.append("oh hello\nim well\nthanks for asking :)\nhow are you?")
    msg = await world.send(anna, "mitski how are u")
    sent = world.client.sent
    assert [m.content for m in sent] == ["oh hello", "im well", "thanks for asking :)", "how are you?"]
    assert replied_to(sent[0]) == msg.id
    assert [replied_to(m) for m in sent[1:]] == [None, None, None]


async def test_one_answer_as_a_block_is_one_message(world, layout):
    layout(shape.BLOCK)
    world.replies.append("this is one line of a longer answer here\nand this is the next line of that answer")
    msg = await world.send(world.people["anna"], "mitski how are u")
    assert world.sent_text() == ["this is one line of a longer answer here\nand this is the next line of that answer"]
    assert replied_to(world.client.sent[0]) == msg.id


# several things


def helper_says(world, answers):
    async def ask_json(system, user, schema, max_tokens=400, think=False):
        return {"answers": answers}

    world.app.helper.ask_json = ask_json


async def test_three_questions_get_answered_in_one_go(world, layout):
    layout(shape.QUICK)
    world.replies.append("im good\nplaying cs\nyeah still in lisbon")
    msgs = await burst(
        world, world.people["anna"], "mitski how are u?", "what are u playing rn?", "do u still live in lisbon?"
    )
    assert world.sent_text() == ["im good", "playing cs", "yeah still in lisbon"]
    assert len(world.prompts) == 1
    assert "Answer every one" in world.prompts[0]
    assert all(q in world.prompts[0] for q in ("how are u?", "what are u playing rn?", "do u still live in lisbon?"))
    assert replied_to(world.client.sent[0]) == msgs[-1].id
    assert [replied_to(m) for m in world.client.sent[1:]] == [None, None]


async def test_answers_as_a_block_are_one_message_on_the_newest(world, layout):
    layout(shape.BLOCK)
    world.replies.append("im good\nplaying cs")
    msgs = await burst(world, world.people["anna"], "mitski how are u?", "what are u playing rn?")
    [sent] = world.client.sent
    assert "im good" in sent.content and "playing cs" in sent.content
    assert replied_to(sent) == msgs[-1].id


async def test_threaded_answers_go_to_the_question_they_answer_even_out_of_order(world, layout):
    layout(shape.THREADED)
    helper_says(world, [2, 1])
    world.replies.append("playing cs\nim good")
    msgs = await burst(world, world.people["anna"], "mitski how are u?", "what are u playing rn?")
    assert world.sent_text() == ["playing cs", "im good"]
    assert [replied_to(m) for m in world.client.sent] == [msgs[1].id, msgs[0].id]


async def test_a_greeting_goes_along_with_the_first_answer(world, layout, monkeypatch):
    layout(shape.THREADED)
    monkeypatch.setattr(shape.random, "random", lambda: 0.99)
    helper_says(world, [0, 1, 2])
    world.replies.append("hey anna\nim good\nplaying cs")
    msgs = await burst(world, world.people["anna"], "mitski how are u?", "what are u playing rn?")
    sent = world.client.sent
    assert [m.content for m in sent] == ["hey anna", "im good", "playing cs"]
    assert [replied_to(m) for m in sent] == [msgs[0].id, None, msgs[1].id]


async def test_lines_about_one_question_stay_together(world, layout, monkeypatch):
    layout(shape.THREADED)
    monkeypatch.setattr(shape.random, "random", lambda: 0.99)
    helper_says(world, [1, 2, 1])
    world.replies.append("im good\nplaying cs\nkinda tired tho")
    msgs = await burst(world, world.people["anna"], "mitski how are u?", "what are u playing rn?")
    sent = world.client.sent
    assert [m.content for m in sent] == ["im good", "kinda tired tho", "playing cs"]
    assert [replied_to(m) for m in sent] == [msgs[0].id, None, msgs[1].id]


async def test_answering_only_one_of_them_replies_to_that_one(world, monkeypatch):
    helper_says(world, [2])
    world.replies.extend(["playing cs", "still one line"])
    msgs = await burst(world, world.people["anna"], "mitski how are u?", "what are u playing rn?")
    assert world.sent_text() == ["playing cs"]
    assert replied_to(world.client.sent[0]) == msgs[1].id


async def test_all_lines_on_one_question_never_thread(world, monkeypatch):
    seen = {}

    def pick(answers, **kw):
        seen.update(kw)
        return shape.QUICK

    monkeypatch.setattr(shape, "pick", pick)
    helper_says(world, [1, 1])
    world.replies.append("im good\nkinda tired tho")
    msgs = await burst(world, world.people["anna"], "mitski how are u?", "what are u playing rn?")
    assert seen["can_thread"] is False
    assert replied_to(world.client.sent[0]) == msgs[0].id


@pytest.mark.parametrize("answers", [None, [1], [3, 1], [0, 0], ["1", "2"], [1, 2, 1]])
async def test_an_unclear_match_never_aims_at_a_single_question(world, layout, answers):
    layout(shape.BLOCK)
    helper_says(world, answers)
    world.replies.append("playing cs\nim good")
    msgs = await burst(world, world.people["anna"], "mitski how are u?", "what are u playing rn?")
    [sent] = world.client.sent
    assert "playing cs" in sent.content and "im good" in sent.content
    assert replied_to(sent) == msgs[-1].id


async def test_threading_is_never_picked_without_a_clear_match(world, monkeypatch):
    seen = {}

    def pick(answers, **kw):
        seen.update(kw)
        return shape.QUICK

    monkeypatch.setattr(shape, "pick", pick)
    helper_says(world, None)
    world.replies.append("one line for both")
    await burst(world, world.people["anna"], "mitski how are u?", "what are u playing rn?")
    assert seen["can_thread"] is False


async def test_a_line_held_back_keeps_the_other_targets_right(world):
    anna = world.people["anna"]
    one, two = world.say(anna, "how are u?"), world.say(anna, "what are u playing?")
    await world.app.sender.send(
        world.channel,
        ["send nudes", "playing cs"],
        parts=[["send nudes"], ["playing cs"]],
        layout=shape.THREADED,
        targets=[(one, True), (two, True)],
    )
    assert world.sent_text() == ["playing cs"]
    assert replied_to(world.client.sent[0]) == two.id


async def test_two_questions_in_one_message_are_both_asked_for(world, layout):
    layout(shape.BLOCK)
    world.replies.append("im good\nplaying cs")
    await world.send(world.people["anna"], "mitski how are u? what are u playing rn?")
    assert "Answer every one" in world.prompts[0]
    assert len(world.client.sent) == 1


async def test_two_questions_in_one_message_cant_be_threaded(world, monkeypatch):
    seen = {}

    def pick(answers, **kw):
        seen.update(kw)
        return shape.QUICK

    monkeypatch.setattr(shape, "pick", pick)
    world.replies.append("im good\nplaying cs")
    await world.send(world.people["anna"], "mitski how are u? what are u playing rn?")
    assert seen["can_thread"] is False


async def test_too_few_answers_gets_one_more_try(world, layout):
    layout(shape.QUICK)
    world.replies.extend(["just one line", "im good\nplaying cs"])
    await burst(world, world.people["anna"], "mitski how are u?", "what are u playing rn?")
    assert world.sent_text() == ["im good", "playing cs"]
    assert "Answer each of these now" in world.prompts[1]
    assert world.app.metrics.done[-1].events["answer all retry"] == 1


async def test_the_first_draft_stays_if_the_retry_is_no_better(world, layout):
    layout(shape.QUICK)
    world.replies.extend(["just one line", "still one line"])
    await burst(world, world.people["anna"], "mitski how are u?", "what are u playing rn?")
    assert world.sent_text() == ["just one line"]


async def test_a_bad_draft_of_several_answers_is_redone(world, layout):
    layout(shape.QUICK)
    world.replies.extend(["as an ai i cant", "fine and playing cs"])
    await burst(world, world.people["anna"], "mitski how are u?", "what are u playing rn?")
    assert world.sent_text() == ["fine and playing cs"]
    assert world.app.metrics.done[-1].events["redo robotic"] == 1


async def test_multi_answer_off_has_no_special_note(world, layout):
    layout(shape.QUICK)
    world.app.cfg.MULTI_ANSWER = False
    world.replies.append("fine and playing cs")
    await burst(world, world.people["anna"], "mitski how are u?", "what are u playing rn?")
    assert "Answer every one" not in world.prompts[0]
    assert world.sent_text() == ["fine and playing cs"]
