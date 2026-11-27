import pytest

from mitski.chat import guard


@pytest.mark.parametrize(
    ("a", "b"), [("yeah i know :)", "yeahhh i know,,"), ("yeah i know", "yh ik"), ("omg same", "OMG SAMEEE")]
)
def test_the_same_thing_typed_differently(a, b):
    assert guard.gist(a) == guard.gist(b)


def test_repeating_herself_is_noticed():
    recent = ["yeah i know :)", "wait what"]
    assert guard.repeats("yh ik", recent) == "yeah i know :)"
    assert guard.repeats("nah thats crazy", recent) is None


def test_a_single_word_only_counts_once_shes_said_it_twice():
    assert guard.repeats("ya", ["ya", "ok"]) is None
    assert guard.repeats("ya", ["ya", "ok", "yeah"]) == "yeah"


@pytest.mark.parametrize("line", ["AHAHAHAHAHAHAA", "lmaooo", "HAHAHA 😭😭", "💀💀💀", "kkkkk", "lol lmao"])
def test_just_laughing(line):
    assert guard.just_laughing(line)


@pytest.mark.parametrize("line", ["lmao what", "haha ok but why", "no way"])
def test_not_just_laughing(line):
    assert not guard.just_laughing(line)


def test_laughing_at_nothing():
    assert guard.laughing_at_nothing(["AHAHAHAHA"], "my dog died today")
    assert not guard.laughing_at_nothing(["AHAHAHAHA"], "i tripped in front of my crush lmao")
    assert not guard.laughing_at_nothing(["AHAHAHAHA"], "my dog ate my homework", joking=True)
    assert not guard.laughing_at_nothing(["AHAHA wait what"], "my dog died today")


def test_an_endless_laugh_is_cut_down():
    assert guard.calm("AHAHAHAHAHAHAHAHAA") == "AHAHAHA"
    assert guard.calm("hahahahahahaha ok") == "hahahah ok"
    assert guard.calm("haha") == "haha"
