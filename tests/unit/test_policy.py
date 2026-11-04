import pytest

from mitski.chat.policy import ADULT_NOTE, SAFE_NOTE, ContentPolicy, asks_if_bot, explicit
from mitski.testing.fakes import FakeChannel, FakeClient, FakeGuild


@pytest.mark.parametrize(
    ("text", "flagged"),
    [
        ("send nudes", True),
        ("im so horny rn", True),
        ("wanna sext", False),
        ("this game is sexy", False),
        ("ur so bad at this game", False),
        ("i got the sex ending lol", True),
        ("dont be a dick", False),
    ],
)
def test_explicit(text, flagged):
    assert explicit(text) is flagged


@pytest.mark.parametrize(
    ("text", "asking"),
    [
        ("are you a bot?", True),
        ("wait r u an ai", True),
        ("am i talking to a bot rn", True),
        ("is mitski an ai", True),
        ("are you actually a bot", True),
        ("r u really human", True),
        ("is this a real person", True),
        ("ur such a bot lol", False),
        ("the bot in this game is broken", False),
    ],
)
def test_asks_if_bot(text, asking):
    assert asks_if_bot(text) is asking


class App:
    def __init__(self, cfg):
        self.cfg = cfg


@pytest.fixture
def channel():
    client = FakeClient()
    return FakeChannel(client, FakeGuild())


@pytest.mark.parametrize(
    ("mode", "nsfw", "minors", "adult"),
    [
        ("nsfw_channels", True, False, True),
        ("nsfw_channels", False, False, False),
        ("nsfw_channels", True, True, False),
        ("never", True, False, False),
    ],
)
def test_adult_only_in_age_restricted_channels(make_cfg, channel, mode, nsfw, minors, adult):
    channel.nsfw = nsfw
    policy = ContentPolicy(App(make_cfg(ADULT_CONTENT=mode)))
    assert policy.adult_ok(channel, minors=minors) is adult
    assert policy.note(channel, minors=minors) == (ADULT_NOTE if adult else SAFE_NOTE)


def test_dms_never_count_as_adult(make_cfg):
    policy = ContentPolicy(App(make_cfg()))
    assert not policy.adult_ok(None)
    assert policy.clean_lines(["hey", "send nudes"], None) == ["hey"]


def test_unknown_mode_falls_back_to_the_default(make_cfg):
    assert make_cfg(ADULT_CONTENT="sure why not").ADULT_CONTENT == "nsfw_channels"
