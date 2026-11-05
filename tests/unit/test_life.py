import asyncio
import itertools
from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace as NS

import pytest

from mitski.social import life
from mitski.social.life import build_day, check_weekly, trip_dates
from mitski.social.routine import Routine, plan_day

THURSDAY = date(2026, 11, 5)
MONDAY = date(2026, 11, 2)


def plan(spells, wake="08:00", bed="00:30", up="08:30", summary="uni then gaming"):
    return {"wake": wake, "spells": spells, "bed": bed, "up_next_day": up, "summary": summary}


def item(a, b, what, level="busy"):
    return {"from": a, "to": b, "level": level, "what": what}


def at(day, hhmm, days=0):
    h, m = map(int, hhmm.split(":"))
    return datetime.combine(day + timedelta(days=days), time(h, m), UTC)


def spells_of(built):
    return [(datetime.fromisoformat(a), datetime.fromisoformat(b), lvl, what) for a, b, lvl, what in built["spells"]]


def test_a_plan_becomes_ordered_spells_with_a_night_after_midnight():
    built = build_day(
        THURSDAY,
        UTC,
        plan([item("14:00", "17:00", "at the library"), item("09:00", "12:30", "In a soil mechanics lecture.")]),
    )
    spells = spells_of(built)
    assert spells[0] == (at(THURSDAY, "00:00"), at(THURSDAY, "08:00"), "asleep", "asleep")
    assert [s[3] for s in spells[1:3]] == ["in a soil mechanics lecture", "at the library"]
    assert spells[-1] == (at(THURSDAY, "00:30", 1), at(THURSDAY, "08:30", 1), "asleep", "asleep")
    assert built["up_next"] == "08:30" and built["summary"] == "uni then gaming"


@pytest.mark.parametrize(
    "what",
    ["finding out she's pregnant", "buying a ferrari", "at the hospital", "moving to berlin", "on a first date"],
)
def test_life_changing_things_never_make_it_into_her_day(what):
    built = build_day(THURSDAY, UTC, plan([item("10:00", "12:00", what)], summary=what))
    assert [s[3] for s in spells_of(built)] == ["asleep", "asleep"]
    assert built["dropped"] == [what] and built["summary"] == ""


def test_travel_only_happens_on_trip_days():
    raw = plan([item("09:00", "12:00", "on a train to porto"), item("13:00", "15:00", "out exploring porto")])
    home = [s[3] for s in spells_of(build_day(THURSDAY, UTC, raw))]
    away = [s[3] for s in spells_of(build_day(THURSDAY, UTC, raw, trip=True))]
    assert "on a train to porto" not in home and "out exploring porto" in home
    assert "on a train to porto" in away


def test_overlaps_bad_times_and_odd_levels_are_dropped_and_spells_stay_awake():
    raw = plan(
        [
            item("09:00", "11:00", "in a lecture"),
            item("10:00", "12:00", "at a lab"),
            item("25:00", "26:00", "nonsense"),
            item("13:00", "13:05", "too short"),
            item("14:00", "16:00", "napping", level="asleep"),
            item("06:00", "09:30", "studying before she's up"),
            item("23:00", "02:00", "playing valorant with friends", level="gaming"),
        ]
    )
    spells = spells_of(build_day(THURSDAY, UTC, raw))
    assert [s[3] for s in spells] == ["asleep", "in a lecture", "playing valorant with friends", "asleep"]
    assert spells[2][1] == at(THURSDAY, "00:30", 1)
    for a, b in itertools.pairwise(spells):
        assert a[1] <= b[0]


def test_yesterdays_wake_up_time_wins_and_no_morning_when_yesterday_was_planned():
    built = build_day(THURSDAY, UTC, plan([], wake="11:00"), wake=time(7, 45), morning=False)
    assert built["wake"] == "07:45"
    assert [s[2] for s in spells_of(built)] == ["asleep"]


def test_sleep_stays_sane():
    built = build_day(THURSDAY, UTC, plan([], bed="03:00", up="06:00"))
    night = spells_of(built)[-1]
    assert night[0] == at(THURSDAY, "03:00", 1) and night[1] - night[0] == timedelta(hours=5)
    early = spells_of(build_day(THURSDAY, UTC, plan([], bed="18:00", up="09:00")))[-1]
    assert early[0] == at(THURSDAY, "20:30")


@pytest.mark.parametrize("raw", [None, "nope", {"wake": "08:00", "spells": []}, plan([], bed="late")])
def test_an_unusable_plan_is_none(raw):
    assert build_day(THURSDAY, UTC, raw) is None


def test_the_weekly_schedule_is_checked():
    items = check_weekly(
        {
            "items": [
                {"day": "mon", "from": "09:00", "to": "11:00", "what": "in a structural analysis lecture"},
                {"day": "mon", "from": "10:00", "to": "12:00", "what": "in an overlapping lab"},
                {"day": "tue", "from": "05:00", "to": "07:00", "what": "in a lecture at dawn"},
                {"day": "wed", "from": "14:00", "to": "15:00", "what": "at her baby shower"},
                {"day": "xyz", "from": "14:00", "to": "15:00", "what": "somewhere"},
                {"day": "thu", "from": "14:00", "to": "16:00", "what": "in a hydraulics lab"},
            ]
        }
    )
    assert [(i["day"], i["what"]) for i in items] == [
        ("mon", "in a structural analysis lecture"),
        ("thu", "in a hydraulics lab"),
    ]
    many = check_weekly(
        {"items": [{"day": d, "from": "08:00", "to": "13:00", "what": "in class"} for d in life.WEEKDAYS] * 2}
    )
    assert len(many) == 7
    longer = check_weekly(
        {
            "items": [
                {"day": d, "from": f, "to": t, "what": "in class"}
                for d in life.WEEKDAYS
                for f, t in (("08:00", "13:00"), ("14:00", "17:00"))
            ]
        }
    )
    assert len(longer) < 14


def test_trips_are_rare_spaced_out_and_never_in_exams():
    weeks = [MONDAY + timedelta(weeks=i) for i in range(400)]
    picked = [trip_dates(w, 7, 0.1, 6, [1, 4], None, "term") for w in weeks]
    share = sum(1 for p in picked if p) / len(weeks)
    assert 0.05 < share < 0.16
    for w, p in zip(weeks, picked, strict=True):
        if p:
            assert p[0].weekday() in (4, 5) and 1 <= (p[1] - p[0]).days + 1 <= 4
            assert p[0] >= w
    assert trip_dates(MONDAY, 7, 1.0, 6, [1, 4], None, "exams") is None
    assert trip_dates(MONDAY, 7, 1.0, 6, [1, 4], MONDAY - timedelta(weeks=2), "term") is None
    assert trip_dates(MONDAY, 7, 1.0, 6, [1, 4], None, "term") == trip_dates(MONDAY, 7, 1.0, 6, [1, 4], None, "term")


class FakeHelper:
    def __init__(self, day=None, week=None):
        self.calls = []
        self.day = day
        self.week = week or {
            "plans": [{"date": "2026-11-06", "what": "dinner with friends"}],
            "trip_where": "",
            "trip_why": "",
        }

    async def ask_json(self, system, text, schema, max_tokens=400, think=False):
        self.calls.append((schema, text))
        if schema is life.TERM_SCHEMA:
            return {
                "phase": "term",
                "until": "2026-12-20",
                "semester": "2026/27 S1",
                "holidays": [{"date": "2026-12-01", "name": "restoration of independence"}],
                "note": "midterms soon",
            }
        if schema is life.WEEKLY_SCHEMA:
            return {"items": [{"day": "thu", "from": "09:00", "to": "12:00", "what": "in a geotechnics lecture"}]}
        if schema is life.WEEK_SCHEMA:
            return self.week
        return self.day


class FakeSearch:
    provider = "ddg"

    def __init__(self):
        self.queries = []

    async def search(self, query):
        self.queries.append(query)
        return "- some result: about lisbon"


class FakeTools:
    async def day_forecast(self, where, day):
        return "light rain, 14 to 18°C"


class FakeClock:
    def __init__(self, when):
        self.when = when

    def now(self):
        return self.when


@pytest.fixture
def make_routine(make_cfg):
    def make(day_plan, **extra):
        cfg = make_cfg(
            ROUTINE=True,
            ROUTINE_PLACE="Lisbon, Portugal",
            ROUTINE_LIFE="a 20 year old civil engineering student in her 3rd year",
            OWNER_ID=7,
            **extra,
        )
        app = NS(
            cfg=cfg,
            clock=FakeClock(datetime(2026, 11, 5, 10, 0, tzinfo=UTC)),
            helper=FakeHelper(day_plan),
            search=FakeSearch(),
            tools=FakeTools(),
            user=None,
            memory=NS(own={"facts": [{"id": 1, "text": "has a dentist appointment on thursday", "cat": "plans"}]}),
        )
        return Routine(app)

    return make


THURSDAY_PLAN = plan(
    [item("09:00", "12:00", "in a geotechnics lecture"), item("21:00", "23:30", "playing cs with friends", "gaming")],
    summary="geotechnics in the morning, cs at night",
)


def simple_plan(routine):
    return plan_day(THURSDAY, routine.week, UTC, routine.cfg.OWNER_ID)


def test_her_model_plans_the_day_and_the_routine_follows_it(make_routine):
    routine = make_routine(THURSDAY_PLAN)
    assert routine._day(THURSDAY, UTC) == simple_plan(routine)
    assert asyncio.run(routine.planner.plan_day(THURSDAY, UTC)) is True
    assert routine.doing() == "in a geotechnics lecture"
    assert "planned by her model" in routine.listing()
    routine.app.clock.when = datetime(2026, 11, 5, 15, 0, tzinfo=UTC)
    assert routine.free and "geotechnics in the morning" in routine.note()
    day_prompt = routine.app.helper.calls[-1][1]
    assert "in a geotechnics lecture" in day_prompt and "light rain" in day_prompt and "dentist" in day_prompt
    assert any("academic calendar" in q for q in routine.app.search.queries)


def test_plans_survive_a_restart(make_routine):
    first = make_routine(THURSDAY_PLAN)
    asyncio.run(first.planner.plan_day(THURSDAY, UTC))
    again = make_routine(None)
    assert again.doing() == "in a geotechnics lecture"


def test_when_her_model_fails_the_simple_plan_stays(make_routine):
    routine = make_routine(None)
    assert asyncio.run(routine.planner.plan_day(THURSDAY, UTC)) is False
    assert routine._day(THURSDAY, UTC) == simple_plan(routine)
    assert "still planning" in routine.listing()


def test_a_trip_only_happens_when_the_code_allows_it_and_never_somewhere_off_limits(make_routine):
    routine = make_routine(THURSDAY_PLAN, ROUTINE_TRIP_CHANCE=1.0)
    routine.app.helper.week = {"plans": [], "trip_where": "porto", "trip_why": "visiting her cousin"}
    asyncio.run(routine.planner.plan_day(THURSDAY, UTC))
    [trip] = routine.planner.data["trips"]
    assert trip["where"] == "porto" and date.fromisoformat(trip["start"]).weekday() in (4, 5)

    bad = make_routine(THURSDAY_PLAN, ROUTINE_TRIP_CHANCE=1.0)
    bad.planner.data = None
    bad.planner.file.path.unlink()
    bad.app.helper.week = {"plans": [], "trip_where": "monaco", "trip_why": "buying a ferrari"}
    asyncio.run(bad.planner.plan_day(THURSDAY, UTC))
    assert bad.planner.data["trips"] == []


def test_redo_clears_today_and_later(make_routine):
    routine = make_routine(THURSDAY_PLAN)
    asyncio.run(routine.planner.plan_day(THURSDAY, UTC))
    routine.planner.redo(THURSDAY)
    assert not routine.planner.planned(THURSDAY)
    assert routine._day(THURSDAY, UTC) == simple_plan(routine)
