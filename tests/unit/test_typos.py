import random

import pytest

from mitski.chat import typos


def one_edit_apart(a, b):
    """True if b is a with one letter changed, dropped, doubled, or two neighbours swapped."""
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        return len(diff) == 1 or (len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]])
    short, long_ = sorted((a, b), key=len)
    return len(long_) - len(short) == 1 and any(long_[:i] + long_[i + 1 :] == short for i in range(len(long_)))


@pytest.mark.parametrize("seed", range(200))
def test_a_typo_is_one_small_slip_in_one_word(seed):
    line = "honestly the lecture today was kinda boring but whatever"
    out, typo = typos.add_typo(line, random.Random(seed))
    if typo is None:
        assert out == line
        return
    wrong, right = typo
    assert out.split() != line.split() and len(out.split()) == len(line.split())
    changed = [(a, b) for a, b in zip(line.split(), out.split(), strict=True) if a != b]
    assert changed == [(right, wrong)]
    assert wrong[0] == right[0] and one_edit_apart(right, wrong)
    assert typos.fix(out, wrong, right) == line


@pytest.mark.parametrize(
    "line",
    [
        "ok lol",
        "LMAO WHAT",
        "https://example.com/something",
        "<@123456789> :sparkles: <a:dance:1234>",
        "[sticker: wave]",
    ],
)
def test_some_things_never_get_a_typo(line):
    for seed in range(50):
        assert typos.add_typo(line, random.Random(seed)) == (line, None)


def test_links_mentions_and_emojis_in_a_line_are_left_alone():
    line = "look at this https://example.com/bridges <@123> :sparkles: amazing"
    for seed in range(100):
        out, typo = typos.add_typo(line, random.Random(seed))
        assert "https://example.com/bridges <@123> :sparkles:" in out
        assert typo is None or typo[1] in ("look", "this", "amazing")


def test_typos_are_occasional_and_more_likely_in_long_messages():
    assert typos.chance("hi", 0.04) < typos.chance("this is a fairly normal message", 0.04)
    assert typos.chance("word " * 40, 0.04) <= 0.04 * 2.5
    assert typos.chance("anything at all here", 0) == 0


def test_a_fix_puts_back_only_the_typo():
    assert typos.fix("teh bridge is teh best", "teh", "the") == "the bridge is teh best"
    assert typos.fix("already fixed", "teh", "the") is None


def test_neighbouring_keys_are_next_to_each_other():
    assert "s" in typos.NEIGHBOURS["a"] and "w" in typos.NEIGHBOURS["e"]
    assert "p" not in typos.NEIGHBOURS["a"]
