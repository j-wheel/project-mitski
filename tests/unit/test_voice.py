import pytest

from mitski.core.voice import asked_about_her, opens_with_she, own_fact_to_you, to_first_person, to_you

NAMES = {"mitski"}


@pytest.mark.parametrize(
    ("line", "fixed"),
    [
        ("mitski is tired", "i'm tired"),
        ("Mitski is tired", "I'm tired"),
        ("mitski thinks ur wrong", "i think ur wrong"),
        ("mitski doesn't do that", "i don't do that"),
        ("mitski's pc is dying", "my pc is dying"),
        ("mitski's still here", "i'm still here"),
        ("mitski's been up all night", "i've been up all night"),
        ("nah mitski was asleep", "nah i was asleep"),
        ("ok and mitski has a cat", "ok and i have a cat"),
        ("lol, mitski tries her best", "lol, i try my best"),
    ],
)
def test_drafts_about_herself_become_first_person(line, fixed):
    assert to_first_person(line, NAMES) == fixed


@pytest.mark.parametrize(
    "line",
    [
        "call me mitski",
        "im mitski",
        "i'm mitski btw",
        "my name is mitski",
        "mitski is me lol",
        "@mitski hi",
        "i love mitski",
        "mitski's new album is so good",
        "mitski concert when",
        "ever listened to mitski",
        "no mention of anyone",
        "",
    ],
)
def test_lines_that_should_keep_her_name(line):
    assert to_first_person(line, NAMES) == line


def test_no_known_name_changes_nothing():
    assert to_first_person("mitski is tired", set()) == "mitski is tired"
    assert to_first_person("mitski is tired", {"ab"}) == "mitski is tired"


@pytest.mark.parametrize(
    ("brief", "fixed"),
    [
        ("she's still here", "i'm still here"),
        ("yes, she's still here", "yes, i'm still here"),
        ("she is from portugal", "i'm from portugal"),
        ("she couldn't find out", "i couldn't find out"),
        ("she has been playing cs", "i have been playing cs"),
        ("she plays cs with her friends", "i play cs with my friends"),
        ("mitski's pc broke and she's sad", "my pc broke and i'm sad"),
    ],
)
def test_a_note_of_what_to_say_can_fix_she_too(brief, fixed):
    assert to_first_person(brief, NAMES, she_too=True) == fixed


@pytest.mark.parametrize(
    ("note", "fixed"),
    [
        (
            "Mitski is playful and she flat-out refuses his asks",
            "You're playful and you flat-out refuse his asks",
        ),
        (
            "they pitch games to mitski, ask if she's played them, and smooth her over when she gets scared",
            "they pitch games to you, ask if you've played them, and smooth you over when you get scared",
        ),
        (
            "only plays games with mitski's group",
            "only plays games with your group",
        ),
        (
            "is in a different time zone (1pm when mitski is up late at night)",
            "is in a different time zone (1pm when you're up late at night)",
        ),
        (
            "He keeps showing screenshots of mitski's DMs, which makes her want to leave",
            "He keeps showing screenshots of your DMs, which makes you want to leave",
        ),
        (
            "he told mitski to kill herself and mitski fires back",
            "he told you to kill yourself and you fire back",
        ),
        (
            "wheeler and mitski talked about his code",
            "wheeler and you talked about his code",
        ),
        (
            "has a partner who can't handle the game mitski was playing",
            "has a partner who can't handle the game you were playing",
        ),
        (
            "Zityu is a friend mitski runs into in #general",
            "Zityu is a friend you run into in #general",
        ),
        (
            "they talked and he offered to walk mitski through it and walk her thru the rest",
            "they talked and he offered to walk you through it and walk you thru the rest",
        ),
        (
            "showed mitski screenshots",
            "showed you screenshots",
        ),
    ],
)
def test_memories_about_her_become_second_person(note, fixed):
    assert to_you(note, NAMES) == fixed


@pytest.mark.parametrize(
    ("note", "fixed"),
    [
        # "she" comes before her name, so it's somebody else
        ("jo said she'll dress up as mitski", "jo said she'll dress up as you"),
        # nobody goes by he or they here, so "her" could be the other person
        ("mitski called her a good boy and she didn't mind", "you called her a good boy and she didn't mind"),
        ("Milk is annoyed when mitski calls her wheeler", "Milk is annoyed when you call her wheeler"),
    ],
)
def test_she_stays_when_it_might_be_someone_else(note, fixed):
    assert to_you(note, NAMES) == fixed


@pytest.mark.parametrize(
    ("note", "fixed"),
    [
        (
            "ugh teased mitski, mitski said she's always in her own world and left",
            "ugh teased you, you said you're always in your own world and left",
        ),
        ("Tsu felt okay and mitski said she was tired", "Tsu felt okay and you said you were tired"),
        ("Tsu said she was tired and mitski said she was too", "Tsu said she was tired and you said she was too"),
    ],
)
def test_she_after_her_own_said_is_her(note, fixed):
    assert to_you(note, NAMES) == fixed


def test_she_stays_when_the_person_goes_by_she():
    note = "they said mitski laughed and she left"
    assert to_you(note, NAMES, she_is_them=True) == "they said you laughed and she left"


def test_facts_can_leave_pronouns_alone():
    assert to_you("his dog likes mitski and she bites", NAMES, pronouns=False) == "his dog likes you and she bites"


@pytest.mark.parametrize(
    "note",
    [
        "listens to mitski a lot",
        "loves mitski's album puberty 2",
        "went to a mitski concert",
        "she has a dog named rex",
        "",
    ],
)
def test_memories_about_the_singer_or_someone_else_stay(note):
    assert to_you(note, NAMES) == note


@pytest.mark.parametrize(
    ("fact", "fixed"),
    [
        ("is 20 years old", "is 20 years old"),
        ("is always in her own world", "is always in your own world"),
        ("loves her friends so much", "loves your friends so much"),
        ("james asked if she was single", "james asked if you were single"),
        ("the girl in her pfp is named haimiya", "the girl in your pfp is named haimiya"),
        ("was reloaded without her memory", "was reloaded without your memory"),
        ("will keep being herself", "will keep being yourself"),
        ("mitski has a cat", "you have a cat"),
    ],
)
def test_her_own_facts_are_always_about_her(fact, fixed):
    assert own_fact_to_you(fact, NAMES) == fixed


def test_rewriting_twice_changes_nothing_more():
    once = to_you("Mitski is playful and they laugh when she teases them", NAMES)
    assert to_you(once, NAMES) == once
    fact = own_fact_to_you("is always in her own world", NAMES)
    assert own_fact_to_you(fact, NAMES) == fact


@pytest.mark.parametrize(
    ("said", "others", "direct"),
    [
        ("are u still here", (), True),
        ("where do you live", (), True),
        ("is she still here", (), False),
        ("what did anna tell u", ("anna",), False),
        ("did he text you", (), False),
        ("whats the capital of australia", (), False),
    ],
)
def test_asked_about_her(said, others, direct):
    assert asked_about_her(said, others) is direct


@pytest.mark.parametrize(
    ("line", "opens"),
    [
        ("she's here", True),
        ("yes she is", True),
        ("lol shes asleep", True),
        ("i think she's here", False),
        ("shell casing", False),
        ("", False),
    ],
)
def test_opens_with_she(line, opens):
    assert opens_with_she(line) is opens
