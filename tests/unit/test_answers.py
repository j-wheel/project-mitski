import pytest

from mitski.brain.answers import answers_it, clean_brief, key_facts


@pytest.mark.parametrize(
    ("brief", "strong", "names"),
    [
        ("It costs 1,500 dollars", {"1500"}, set()),
        ("The patch dropped on March 3", {"mar", "3"}, set()),
        ("you may want to sleep", set(), set()),
        ("He said NASA did it", {"nasa"}, set()),
        ("Tell them Valve released Deadlock", set(), {"valve", "deadlock"}),
        ("Sure. Okay then", set(), set()),
        ("the game is Big and big", set(), set()),
    ],
)
def test_key_facts(brief, strong, names):
    facts = key_facts(brief)
    assert facts.strong == strong
    assert facts.names == names


@pytest.mark.parametrize(
    ("lines", "brief", "strict", "expected"),
    [
        (["its like 1500 bucks"], "It costs 1,500 dollars", False, True),
        (["its expensive"], "It costs 1,500 dollars", False, False),
        (["idk tbh?"], "It costs 1,500 dollars", False, False),
        (["sure thing"], "you may want to sleep", False, True),
        (["valve made it lol"], "Tell them Valve released Deadlock", True, True),
        (["valve made it lol"], "Valve released Deadlock", True, False),
        (["no clue"], "Valve released Deadlock", True, False),
        (["it came out in march"], "It came out on March 3", True, True),
        ([""], "anything", False, False),
    ],
)
def test_answers_it(lines, brief, strict, expected):
    assert answers_it(lines, brief, strict) is expected


@pytest.mark.parametrize(
    ("brief", "kept"),
    [
        ("tell him it's at 8", True),
        ("yes, i'm still here", True),
        ("I'm here to help if you need anything", False),
        ("As an AI I can't", False),
        ("", False),
    ],
)
def test_clean_brief(brief, kept):
    assert bool(clean_brief(brief)) is kept
