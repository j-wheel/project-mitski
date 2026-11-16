import pytest

from mitski.core.identity import Identity
from mitski.llm.client import drop_unfinished, stopped_at_limit


@pytest.fixture
def her(make_cfg):
    return Identity(make_cfg(HER_AGE=20, HER_GENDER="girl", HER_FROM="Portugal", HER_CITY="Lisbon"))


@pytest.mark.parametrize(
    "line",
    [
        "im 21 lol",
        "i'm 19 btw",
        "im 22 years old",
        "i just turned 21",
        "im a guy",
        "as a guy i think",
        "im from spain",
        "i live in brazil",
        "im american",
    ],
)
def test_wrong_about_herself(her, line):
    assert her.wrong(line)


@pytest.mark.parametrize(
    "line",
    [
        "im 20 lol",
        "im 21 mins away",
        "im 5 minutes late",
        "my brother is 21",
        "im a girl",
        "im portuguese",
        "i live in lisbon",
        "im from portugal",
        "im french fries obsessed",
        "im in class rn",
        "im 2 games in",
        "hey",
    ],
)
def test_right_or_not_about_her(her, line):
    assert her.wrong(line) is None


@pytest.mark.parametrize(
    ("fact", "wrong"),
    [
        ("is 21 years old", True),
        ("is from brazil", True),
        ("is 20 years old", False),
        ("lives in lisbon", False),
        ("plays cs2 a lot", False),
    ],
)
def test_what_she_remembers_about_herself(her, fact, wrong):
    assert bool(her.wrong_fact(fact)) is wrong


def test_the_facts_are_spelled_out(her):
    line = her.line()
    assert "you're 20" in line and "a girl" in line and "from Portugal" in line and "Lisbon" in line


def test_nothing_set_nothing_checked(make_cfg):
    nobody = Identity(make_cfg())
    assert nobody.line() == "" and nobody.wrong("im 35 and from spain") is None


def test_a_cut_off_answer_keeps_what_was_finished():
    assert drop_unfinished("one line\nanother one\nand this got cu") == "one line\nanother one"
    assert drop_unfinished("It shows a cat. It is sitting on a ch") == "It shows a cat."


def test_running_out_of_tokens_is_noticed():
    assert stopped_at_limit({"stop_type": "limit"})
    assert not stopped_at_limit({"stop_type": "eos", "tokens_predicted": 400}, 400)
    assert stopped_at_limit({"tokens_predicted": 400}, 400)
