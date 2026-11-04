import pytest

from mitski.social.ages import Signal, read_signal, strongest


@pytest.mark.parametrize(
    ("text", "age", "minor"),
    [
        ("15", 15, True),
        ("13-15", 13, True),
        ("16-17", 16, True),
        ("16 y/o", 16, True),
        ("im 14", 14, True),
        ("she/her | 16 | gamer", 16, True),
        ("anna (15)", 15, True),
        ("13+", 13, True),
        ("-18", None, True),
        ("18-", None, True),
        ("Minor", None, True),
        ("under 18", None, True),
        ("high schooler", None, True),
        ("18+", None, False),
        ("18-25", None, False),
        ("21", None, False),
        ("Level 15", None, False),
        ("top 10 player", None, False),
        ("2015 veteran", None, False),
        ("", None, False),
    ],
)
def test_read_signal(text, age, minor):
    signal = read_signal(text, "their role")
    assert (signal is not None) is minor
    if minor:
        assert signal.age == age


def test_strongest_prefers_a_stated_age():
    assert strongest([Signal(None, "a"), Signal(16, "b"), Signal(14, "c")]).age == 14
    assert strongest([None, None]) is None
