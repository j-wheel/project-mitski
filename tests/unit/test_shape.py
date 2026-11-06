import random
from collections import Counter

import pytest

from mitski.chat import shape
from mitski.chat.addressing import needs_own_answer, split_questions
from mitski.chat.pipeline import too_few_answers
from mitski.chat.style import Style

PLAIN = {"SLANG": 0, "LOWERCASE": False, "NO_APOSTROPHES": 0, "SPLIT_CHANCE": 0, "STRETCH_CHANCE": 0, "FLAIR_CHANCE": 0}
LINE = "this is a fairly normal length line for her to send"


def many(answers, n=400, **kw):
    rng = random.Random(5)
    return Counter(shape.pick(answers, rng=rng, **kw) for _ in range(n))


@pytest.mark.parametrize(
    "answers",
    [
        [["just one line"]],
        [["oh hi", "whats up"]],
        [[LINE, "[sticker: wave]"], [LINE]],
    ],
)
def test_short_replies_are_always_quick(answers):
    assert set(many(answers)) == {shape.QUICK}


def test_one_answer_is_mostly_quick_messages():
    seen = many([[LINE, LINE]])
    assert seen[shape.QUICK] > 3 * seen[shape.BLOCK] > 0
    assert seen[shape.THREADED] == 0


def test_several_answers_can_take_any_shape():
    seen = many([[LINE], [LINE]], can_thread=True)
    assert all(seen[k] > 40 for k in (shape.QUICK, shape.BLOCK, shape.THREADED))


def test_no_replying_to_each_one_when_there_is_nothing_to_reply_to():
    assert many([[LINE], [LINE]], can_thread=False)[shape.THREADED] == 0


def test_a_long_multi_answer_leans_to_one_message():
    seen = many([[LINE * 4], [LINE * 4]])
    assert seen[shape.BLOCK] > 2 * seen[shape.QUICK]


def test_a_busy_chat_leans_away_from_scattered_messages():
    calm, busy = many([[LINE], [LINE]]), many([[LINE], [LINE]], crowded=True)
    assert busy[shape.QUICK] < calm[shape.QUICK]


def test_serious_replies_lean_to_one_message():
    calm, serious = many([[LINE, LINE]]), many([[LINE, LINE]], serious=True)
    assert serious[shape.BLOCK] > calm[shape.BLOCK]


def test_a_longer_reply_mostly_goes_out_as_one_proper_message():
    seen = many([[LINE, LINE, LINE]], longer=True)
    assert seen[shape.BLOCK] > seen[shape.QUICK] > 0


@pytest.mark.parametrize(
    ("text", "pieces"),
    [
        ("how are u? what are u playing rn?", ["how are u?", "what are u playing rn?"]),
        ("how are u?\ndo u still live in lisbon?", ["how are u?", "do u still live in lisbon?"]),
        ("do u like valorant? like do u play valorant?", ["do u like valorant? like do u play valorant?"]),
        ("i got a new job. what are u up to?", ["i got a new job. what are u up to?"]),
        ("what? huh?", ["what? huh?"]),
        ("just saying hi", ["just saying hi"]),
    ],
)
def test_split_questions(text, pieces):
    assert split_questions(text) == pieces


@pytest.mark.parametrize(
    ("text", "own"),
    [
        ("what are u playing rn?", True),
        ("can you send me the clip", True),
        ("DONT LEAVE ME I'll get separation anxiety", False),
        ("😭 😭", False),
        ("woah she went therapy mode", False),
        ("lol", False),
        ("hii", False),
    ],
)
def test_only_questions_and_requests_need_their_own_answer(text, own):
    assert needs_own_answer(text) is own


@pytest.mark.parametrize(
    ("lines", "questions", "retry"),
    [(1, 2, True), (1, 3, True), (2, 3, False), (2, 4, True), (3, 3, False), (3, 2, False)],
)
def test_texting_merges_answers_so_only_clearly_too_few_gets_a_retry(lines, questions, retry):
    assert too_few_answers(lines, questions) is retry


def test_a_block_puts_a_blank_line_between_answers(make_cfg):
    out = Style(make_cfg(**PLAIN)).joined([["first answer"], ["second answer"]], rng=random.Random(2))
    assert out == "first answer\n\nsecond answer"


class Always(random.Random):
    def random(self):
        return 0.0


def test_a_block_can_run_short_lines_of_one_answer_together(make_cfg):
    out = Style(make_cfg(**PLAIN)).joined([["oh im well!", "glad ur good too"], ["been a while"]], rng=Always())
    assert out == "oh im well! glad ur good too\n\nbeen a while"
    out = Style(make_cfg(**PLAIN)).joined([["oh im well", "glad ur good too"]], rng=Always())
    assert out == "oh im well, glad ur good too"


def test_long_lines_stay_on_their_own_line(make_cfg):
    out = Style(make_cfg(**PLAIN)).joined([[LINE, LINE]], rng=Always())
    assert out == f"{LINE}\n{LINE}"
