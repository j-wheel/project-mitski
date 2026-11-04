import pytest

from mitski.memory.heuristics import clean_name, junk_fact, norm_cat


@pytest.mark.parametrize(
    ("fact", "junk"),
    [
        ("lol", True),
        ("ok", True),
        ("is tired right now", True),
        ("said hi to everyone", True),
        ("has a dog named rex", False),
        ("works as a nurse", False),
    ],
)
def test_junk_fact(fact, junk):
    assert junk_fact(fact) is junk


@pytest.mark.parametrize(("raw", "name"), [("  @Anna!! ", "@Anna"), ("", None)])
def test_clean_name(raw, name):
    assert clean_name(raw) == name


@pytest.mark.parametrize(("raw", "cat"), [("Games", "games"), ("nonsense", "other")])
def test_norm_cat(raw, cat):
    assert norm_cat(raw) == cat
