import random
from types import SimpleNamespace as NS

import pytest

from mitski.chat import convo

HER, ANNA, BOB = 1, 2, 3


def msg(author, content="hey"):
    return NS(author=NS(id=author), content=content)


class Rolls(random.Random):
    def __init__(self, value):
        super().__init__(0)
        self.value = value

    def random(self):
        return self.value


@pytest.mark.parametrize(
    ("after", "explicit", "roll", "crowded", "kind"),
    [
        ([], True, 0.1, False, "reply"),
        ([], True, 0.9, False, "plain"),
        ([ANNA, ANNA, ANNA], False, 0.9, False, "reply"),
        ([BOB], False, 0.01, False, "ping"),
        ([BOB], False, 0.99, False, "reply"),
        ([], False, 0.99, True, "reply"),
    ],
)
def test_decide(after, explicit, roll, crowded, kind):
    d = convo.decide(msg(ANNA), after, HER, explicit=explicit, crowded=crowded, rng=Rolls(roll))
    assert d.kind == kind


def test_decide_without_anyone_is_plain():
    assert convo.decide(None, [ANNA], HER).kind == "plain"


@pytest.mark.parametrize(
    ("after", "limit", "late"),
    [([ANNA, BOB, ANNA], 3, True), ([ANNA, HER, BOB], 3, False), ([ANNA] * 10, 0, False)],
)
def test_too_late(after, limit, late):
    assert convo.too_late(after, HER, limit) is late


@pytest.mark.parametrize(
    ("lines", "at_end", "expected"),
    [
        (["hi", "whats up"], False, ["<@7> hi", "whats up"]),
        (["hi", "whats up"], True, ["hi", "whats up <@7>"]),
        (["[sticker: wave]", "hi"], False, ["[sticker: wave]", "<@7> hi"]),
        (["<@7> already"], False, ["<@7> already"]),
        ([], False, []),
    ],
)
def test_add_ping(lines, at_end, expected):
    assert convo.add_ping(lines, 7, at_end) == expected


def test_real_pings_only_swaps_allowed_people():
    anna, bob = NS(id=10), NS(id=11)
    line, pinged = convo.real_pings("@anna and @bob.", {"anna": anna, "bob": bob}, lambda u: u is anna)
    assert line == "<@10> and bob."
    assert pinged == [anna]


@pytest.mark.parametrize(
    ("orders", "names", "forbidden"),
    [
        (["dont ping anna"], {"anna"}, True),
        (["ping anna whenever"], {"anna"}, False),
        (["never ping bob"], {"anna"}, False),
        (["be nice"], {"anna"}, False),
    ],
)
def test_ping_forbidden(orders, names, forbidden):
    assert convo.ping_forbidden(orders, names) is forbidden
