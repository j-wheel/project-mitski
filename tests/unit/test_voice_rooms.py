from types import SimpleNamespace as NS

import pytest

from mitski.voice.rooms import RoomPicker, room_score, word_in


def room(name, limit=0, position=0):
    return NS(name=name, user_limit=limit, position=position)


@pytest.mark.parametrize(
    ("better", "worse"),
    [("General", "AFK"), ("chill vc", "music bot"), ("gaming", "duo room 2"), ("lounge", "Staff only")],
)
def test_room_score_prefers_hangout_rooms(better, worse):
    assert room_score(room(better)) > room_score(room(worse, limit=2 if "duo" in worse else 0))


@pytest.mark.parametrize(
    ("name", "text", "found"),
    [("anna", "join where anna is", True), ("ann", "join where anna is", False), ("al", "al is here", False)],
)
def test_word_in(name, text, found):
    assert word_in(name, text) is found


def test_picks_the_busiest_room_when_nothing_is_named(monkeypatch):
    import mitski.voice.rooms as rooms

    quiet, busy = room("one"), room("two")
    monkeypatch.setattr(rooms, "joinable", lambda c: True)
    people = {id(quiet): [1], id(busy): [1, 2, 3]}
    picker = RoomPicker(lambda c: people[id(c)])
    msg = NS(
        guild=NS(voice_channels=[quiet, busy], get_member=lambda uid: None),
        content="hop in vc",
        channel_mentions=[],
        mentions=[],
        author=NS(voice=None),
    )
    assert picker.pick(msg, me_id=0) == (busy, "the vc with the most people")
