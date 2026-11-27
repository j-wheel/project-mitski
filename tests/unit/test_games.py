import random
from datetime import UTC, date

import pytest

from mitski.social import games
from mitski.social import routine as rt
from mitski.social.life import build_day

HERS = ["Counter-Strike 2", "VALORANT", "Roblox", "Minecraft", "League of Legends", "Honkai: Star Rail", "The Sims 4"]


@pytest.mark.parametrize(
    ("text", "game"),
    [
        ("in a ranked cs match", "Counter-Strike 2"),
        ("playing valorant with friends", "VALORANT"),
        ("grinding val", "VALORANT"),
        ("playing league with her duo", "League of Legends"),
        ("on roblox with friends", "Roblox"),
        ("building in minecraft", "Minecraft"),
        ("doing hsr dailies", "Honkai: Star Rail"),
        ("playing the sims", "The Sims 4"),
        ("in a soil mechanics lecture", ""),
        ("", ""),
    ],
)
def test_which_game_a_session_is(text, game):
    assert games.match(text, HERS) == game


def test_sessions_read_like_her_plan():
    text = games.session("Minecraft", random.Random(1))
    assert "Minecraft" in text and text.startswith(("playing", "in a", "grinding"))


def test_the_simple_plan_says_which_game():
    week = rt.Week(None, None, "", (), (0, 0), tuple(HERS), (2, 2))
    spells = rt.plan_day(date(2026, 11, 26), week, UTC, seed="x")
    playing = [s for s in spells if s.level == rt.GAMING]
    assert playing and all(s.game in HERS and s.game in s.what for s in playing)


def test_her_models_plan_keeps_the_game_it_picked():
    raw = {
        "wake": "09:00",
        "spells": [
            {"from": "20:00", "to": "22:00", "level": "gaming", "what": "ranked with friends", "game": "valorant"},
            {"from": "14:00", "to": "15:00", "level": "busy", "what": "at the library", "game": ""},
            {"from": "22:30", "to": "23:30", "level": "gaming", "what": "a few rounds of cs", "game": "something else"},
        ],
        "bed": "01:00",
        "up_next_day": "09:00",
        "summary": "uni then games",
    }
    built = build_day(date(2026, 11, 26), UTC, raw, played=tuple(HERS))
    kinds = {s[3]: s[4] for s in built["spells"] if s[2] != "asleep"}
    assert kinds == {"ranked with friends": "VALORANT", "at the library": "", "a few rounds of cs": "Counter-Strike 2"}
