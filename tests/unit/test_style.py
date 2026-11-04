import random

import pytest

from mitski.chat.style import SPLIT_ALLOWANCE, Style

PLAIN = {"SLANG": 0, "LOWERCASE": False, "NO_APOSTROPHES": 0, "SPLIT_CHANCE": 0, "STRETCH_CHANCE": 0, "FLAIR_CHANCE": 0}


def test_plain_style_leaves_words_alone(make_cfg):
    out = Style(make_cfg(**PLAIN)).reply(["I do not know what you mean."], rng=random.Random(1))
    assert out == ["I do not know what you mean"]


def test_lowercase(make_cfg):
    out = Style(make_cfg(**{**PLAIN, "LOWERCASE": True})).reply(["Hello There"], rng=random.Random(1))
    assert out == ["hello there"]


@pytest.mark.parametrize("seed", range(5))
def test_splitting_never_runs_past_the_allowance(make_cfg, seed):
    style = Style(make_cfg(MAX_LINES=3, SPLIT_CHANCE=1.0))
    out = style.reply([f"line number {i}, with a clause, and another" for i in range(8)], rng=random.Random(seed))
    assert 1 <= len(out) <= 3 + SPLIT_ALLOWANCE


def test_same_seed_same_output(make_cfg):
    style = Style(make_cfg())
    lines = ["I don't know, because it's really late right now"]
    assert style.reply(lines, rng=random.Random(7)) == style.reply(lines, rng=random.Random(7))


def test_joined_keeps_both_answers(make_cfg):
    out = Style(make_cfg(**PLAIN)).joined([["first thing"], ["second thing"]], rng=random.Random(2))
    assert "first thing" in out and "second thing" in out
