from datetime import datetime, timedelta

import pytest

from mitski.reminders.store import Reminders
from mitski.reminders.timing import delay_minutes, describe, due_time

NOW = datetime(2026, 11, 3, 14, 0)


@pytest.mark.parametrize(
    ("text", "minutes"),
    [
        ("remind me in 2 hours", 120),
        ("in 30 min", 30),
        ("in half an hour", 30),
        ("in an hour and 15 minutes", 75),
        ("in 1h30m", 90),
        ("in 2 days", 2880),
        ("tomorrow", None),
        ("remind me about it", None),
    ],
)
def test_delay_minutes(text, minutes):
    assert delay_minutes(text) == minutes


@pytest.mark.parametrize(
    ("text", "plan", "expected"),
    [
        ("in 10 min", {}, NOW + timedelta(minutes=10)),
        ("later", {"in_minutes": 45}, NOW + timedelta(minutes=45)),
        ("at 18:30", {"at_time": "18:30"}, NOW.replace(hour=18, minute=30)),
        ("at 9", {"at_time": "09:00"}, (NOW + timedelta(days=1)).replace(hour=9, minute=0)),
        ("on the 5th", {"at_time": "12:00", "on_date": "2026-11-05"}, datetime(2026, 11, 5, 12, 0)),
        ("whenever", {"at_time": "25:00"}, None),
        ("whenever", {}, None),
    ],
)
def test_due_time(text, plan, expected):
    assert due_time(text, plan, NOW) == expected


@pytest.mark.parametrize(
    ("delta", "fragment"),
    [
        (timedelta(minutes=5), "in 5 min"),
        (timedelta(hours=2), "in 2 hours"),
        (timedelta(hours=20), "tomorrow"),
        (timedelta(days=4), "in 4 days"),
    ],
)
def test_describe(delta, fragment):
    assert fragment in describe(NOW + delta, NOW)


def test_store_round_trips(make_cfg):
    store = Reminders(make_cfg())
    first = store.add(1, 2, 3, 4, due=100.0, what="drink water", msg_id=9)
    store.add(5, 5, 3, None, due=50.0, what="sleep")
    again = Reminders(make_cfg())
    again.load()
    assert [r.what for r in again.upcoming()] == ["sleep", "drink water"]
    assert again.by_source(9).id == first.id
    assert [r.what for r in again.due_now(now=75.0)] == ["sleep"]
    assert again.cancel([first.id])[0].what == "drink water"
    assert again.next_id == 3
