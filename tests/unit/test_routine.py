import itertools
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace as NS

import pytest

from mitski.social import routine as rt
from mitski.social.routine import ASLEEP, BUSY, GAMING, Routine, Week, plan_day

WEEK = Week(
    sleep=(rt._clock_time("02:00"), rt._clock_time("10:00")),
    busy=(rt._clock_time("11:00"), rt._clock_time("16:00")),
    busy_what="at uni",
    errands=("out shopping",),
    errands_per_day=(1, 3),
    games=("in a ranked game",),
    games_per_day=(0, 2),
)
MONDAY = date(2026, 11, 2)
SATURDAY = date(2026, 11, 7)


class FakeClock:
    def __init__(self, when):
        self.when = when

    def now(self):
        return self.when


@pytest.fixture
def routine(make_cfg):
    cfg = make_cfg(
        ROUTINE=True,
        ROUTINE_SLEEP=["02:00", "10:00"],
        ROUTINE_BUSY=["11:00", "16:00"],
        ROUTINE_LOOK_BUSY=[600, 600],
        ROUTINE_LOOK_GAMING=[100, 100],
        ROUTINE_STAY=[120, 120],
        OWNER_ID=7,
    )
    return Routine(NS(cfg=cfg, clock=FakeClock(datetime(2026, 11, 2, 20, 0, tzinfo=UTC))))


def at(routine, hour, minute=0):
    routine.app.clock.when = datetime(2026, 11, 2, hour, minute, tzinfo=UTC)


def test_the_same_day_always_comes_out_the_same():
    assert plan_day(MONDAY, WEEK, UTC, "a") == plan_day(MONDAY, WEEK, UTC, "a")
    assert plan_day(MONDAY, WEEK, UTC, "a") != plan_day(MONDAY + timedelta(days=1), WEEK, UTC, "a")


@pytest.mark.parametrize("offset", range(30))
def test_spells_never_overlap_and_stay_in_order(offset):
    spells = plan_day(MONDAY + timedelta(days=offset), WEEK, UTC, "x")
    assert [s.level for s in spells].count(ASLEEP) == 1
    for a, b in itertools.pairwise(spells):
        assert a.end <= b.start
    assert all(s.start < s.end for s in spells)


@pytest.mark.parametrize("offset", range(30))
def test_nothing_repeats_in_a_day_and_errands_end_at_a_sane_hour(offset):
    week = Week(WEEK.sleep, None, "", ("a", "b", "c"), (3, 3), ("g",), (2, 2))
    spells = plan_day(MONDAY + timedelta(days=offset), week, UTC, "x")
    done = [s.what for s in spells]
    assert len(done) == len(set(done))
    assert all(s.end.time() <= rt.ERRANDS_DONE_BY for s in spells if s.level == BUSY)


def test_she_sleeps_every_night_near_the_set_time():
    [night] = [s for s in plan_day(MONDAY, WEEK, UTC, "x") if s.level == ASLEEP]
    assert night.start.hour in (1, 2) and night.end.hour in (9, 10)


def test_a_night_can_run_past_midnight():
    week = Week((rt._clock_time("23:30"), rt._clock_time("08:00")), None, "", (), (0, 0), (), (0, 0))
    [night] = plan_day(MONDAY, week, UTC, "x")
    assert night.start.date() == MONDAY and night.end.date() == MONDAY + timedelta(days=1)


def test_most_weekdays_have_the_long_block_with_a_break_and_weekends_dont():
    days = [MONDAY + timedelta(days=i * 7) for i in range(30)]
    busy = [[s for s in plan_day(d, WEEK, UTC, "x") if s.what == "at uni"] for d in days]
    assert sum(1 for b in busy if b) > 20
    assert all(len(b) in (0, 2) for b in busy)
    assert all(b[1].start > b[0].end for b in busy if b)
    weekends = [SATURDAY + timedelta(days=i * 7) for i in range(30)]
    assert not any(s.what == "at uni" for d in weekends for s in plan_day(d, WEEK, UTC, "x"))


def test_off_means_always_free(routine):
    routine.on = False
    at(routine, 4)
    assert routine.free and routine.looking()
    assert routine.status() == routine.cfg.STATUS


def test_free_means_she_notices_right_away(routine):
    routine.days = {MONDAY: []}
    assert routine.free and routine.looking()
    assert routine.notice_at("chat") == routine.stamp()


def forced(routine, level, what="out", hours=3):
    now = routine.now()
    routine.forced = rt.Spell(now, now + timedelta(hours=hours), level, what)


def test_a_dm_gets_noticed_before_a_ping_before_a_chat_message(routine, monkeypatch):
    monkeypatch.setattr(rt.random, "uniform", lambda a, b: (a + b) / 2)
    forced(routine, BUSY)
    t = routine.stamp()
    assert routine.notice_at("dm") - t < routine.notice_at("ping") - t < routine.notice_at("chat") - t


def test_gaming_means_shorter_gaps_than_being_busy(routine, monkeypatch):
    monkeypatch.setattr(rt.random, "uniform", lambda a, b: (a + b) / 2)
    forced(routine, BUSY)
    busy = routine.notice_at("chat") - routine.stamp()
    routine.next_look = 0
    forced(routine, GAMING)
    assert routine.notice_at("chat") - routine.stamp() < busy


def test_a_look_opens_a_window_for_everyone_then_closes(routine):
    forced(routine, BUSY)
    assert not routine.looking()
    routine.look()
    assert routine.looking()
    routine.app.clock.when += timedelta(seconds=121)
    assert not routine.looking()


def test_chatting_keeps_her_around_but_not_forever(routine):
    forced(routine, BUSY, hours=5)
    routine.look()
    for _ in range(100):
        routine.app.clock.when += timedelta(seconds=50)
        routine.keep_around()
    assert not routine.looking()


def test_being_asleep_waits_for_morning_unless_its_the_owner(routine):
    forced(routine, ASLEEP, "asleep", hours=6)
    spell = routine.spell()
    assert routine.notice_at("dm") >= spell.end.timestamp()
    assert routine.notice_at("ping") >= spell.end.timestamp()
    assert routine.notice_at("dm", owner=True) <= routine.stamp() + rt.OWNER_MAX_WAIT


def test_the_owner_never_waits_long_when_she_is_busy(routine):
    forced(routine, BUSY)
    routine.next_look = routine.stamp() + 3000
    assert routine.notice_at("chat", owner=True) <= routine.stamp() + rt.OWNER_MAX_WAIT


def test_presence_follows_the_routine(routine):
    routine.cfg.ROUTINE_PRESENCE = True
    forced(routine, ASLEEP)
    assert routine.status() == "invisible"
    forced(routine, BUSY)
    assert routine.status() == "idle"
    forced(routine, GAMING)
    assert routine.status() == routine.cfg.STATUS
    routine.cfg.ROUTINE_PRESENCE = False
    forced(routine, ASLEEP)
    assert routine.status() == routine.cfg.STATUS


def test_only_being_asleep_or_busy_stops_hanging_out(routine):
    forced(routine, GAMING)
    assert routine.can_hang_out and not routine.free
    forced(routine, BUSY)
    assert not routine.can_hang_out


def test_set_free_and_set_busy_override_the_plan(routine):
    routine.set_busy(30, "at the dentist")
    assert routine.doing() == "at the dentist"
    routine.set_free(60)
    assert routine.free
    routine.set_busy(10)
    assert not routine.free
    routine.app.clock.when += timedelta(minutes=11)
    routine.spell()
    assert routine.forced is None


@pytest.mark.parametrize(
    ("seconds", "said"),
    [(600, "about 10 minutes"), (7200, "about 2 hours")],
)
def test_seen_late_says_how_long(routine, seconds, said):
    assert said in routine.seen_late(seconds, "out")


def test_the_listing_shows_what_she_is_doing(routine):
    forced(routine, BUSY, "out with a friend")
    assert "out with a friend until" in routine.listing()
    routine.on = False
    assert "off" in routine.listing()
