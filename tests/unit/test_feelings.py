import time
from datetime import UTC, datetime
from types import SimpleNamespace as NS

import pytest

from mitski.social import feelings as fe
from mitski.social.feelings import Feelings, Mood, add, drifted, effects, fresh_regard, hurt_now, tier

OWNER, ANNA, KID = 1, 2, 3
NOW = 1_800_000_000.0


class StubMemory:
    def __init__(self):
        self.people = {}

    def get(self, uid):
        return self.people.get(str(uid))

    def current_age(self, d):
        return d.get("age")

    def call_name(self, d):
        return None


@pytest.fixture
def make(make_cfg):
    def build(**cfg):
        app = NS(
            cfg=make_cfg(**cfg),
            memory=StubMemory(),
            ages=NS(is_minor=lambda u: getattr(u, "id", u) == KID),
            owner=NS(is_owner=lambda u: getattr(u, "id", u) == OWNER),
            clock=NS(now=lambda: datetime.now(UTC)),
        )
        f = Feelings(app)
        for uid, name in ((OWNER, "boss"), (ANNA, "anna"), (KID, "kid")):
            app.memory.people[str(uid)] = {"name": name, "talks": 50, "last_seen": time.time()}
        app.memory.people[str(KID)]["age"] = 15
        return f

    return build


def person(f, uid):
    return f.memory.get(uid)


def regard(**kw):
    return {**fresh_regard(), **kw}


def test_new_people_start_neutral_and_an_old_vibe_carries_over():
    assert fresh_regard()["like"] == 0 and fresh_regard()["trust"] > 0
    d = {"vibe": 3.0, "talks": 100}
    r = fresh_regard(d)
    assert r["like"] == 18 and "vibe" not in d and r["trust"] > fresh_regard()["trust"]


def test_bad_moments_weigh_more_than_good_ones():
    r = regard()
    good, bad = effects("compliment_her", 2, r, NOW), effects("insulted_her", 2, r, NOW)
    assert abs(bad["like"]) > 2 * good["like"] and bad["hurt"] > 0


def test_the_same_compliment_wears_off():
    r = regard()
    first = effects("compliment_her", 1, r, NOW)["like"]
    r["events"] = [{"t": NOW - 60, "kind": "compliment_her"}, {"t": NOW - 30, "kind": "compliment_her"}]
    assert effects("compliment_her", 1, r, NOW)["like"] < first / 2


def test_a_roast_from_a_close_friend_stings_less():
    stranger, friend = regard(), regard(like=50, trust=60)
    assert effects("insulted_her", 1, friend, NOW)["hurt"] < effects("insulted_her", 1, stranger, NOW)["hurt"]


def test_sweet_talk_from_someone_she_dislikes_counts_less():
    assert effects("kindness", 1, regard(like=-40), NOW)["like"] < effects("kindness", 1, regard(), NOW)["like"]


def test_too_much_affection_too_soon_is_suspicious():
    trusted = effects("genuine_affection", 3, regard(trust=60), NOW)
    early = effects("genuine_affection", 3, regard(trust=15), NOW, early=True)
    assert early["like"] < trusted["like"] / 2 and early["trust"] < 0


def test_no_chemistry_ever_with_a_minor():
    assert "spark" not in effects("flirted_nicely", 3, regard(trust=60), NOW, minor=True)


def test_it_gets_harder_to_move_further_towards_an_extreme():
    middle, high = regard(), regard(like=90)
    assert add(middle, "like", 10) > add(high, "like", 10) > 0
    assert add(regard(like=90), "like", -10) == -10


def test_hurt_fades_and_old_friends_drift_back_to_neutral():
    r = regard(hurt=40, hurt_t=NOW)
    assert hurt_now(r, NOW + 18 * 3600, 18) == pytest.approx(20)
    like, spark = drifted(regard(like=60, spark=50), NOW - 90 * 86400, NOW)
    assert 0 < like < 60 and spark < 50
    assert drifted(regard(like=60), NOW - 5 * 86400, NOW)[0] == 60


def test_nobody_can_flatter_their_way_up_in_a_day(make):
    f = make(LIKE_DAILY_MAX=15)
    d = person(f, ANNA)
    for _ in range(20):
        f.apply(NS(id=ANNA), d, "supported_her", 3, "had your back")
    assert d["regard"]["like"] <= 15.01


def test_her_owner_never_drops_below_a_floor(make):
    f = make()
    d = person(f, OWNER)
    for _ in range(10):
        f.apply(NS(id=OWNER), d, "threatened_her", 3, "threatened you")
    assert d["regard"]["like"] >= fe.OWNER_FLOOR["like"] and d["regard"]["trust"] >= fe.OWNER_FLOOR["trust"]


def test_a_minor_never_builds_chemistry(make):
    f = make()
    d = person(f, KID)
    for _ in range(5):
        f.apply(NS(id=KID), d, "flirted_nicely", 3, "flirted")
    assert d["regard"]["spark"] == 0
    assert "no flirting" in f.regard_note(NS(id=KID), d, "kid")


def test_judged_moments_need_a_real_quote_from_them(make):
    f = make()
    d = person(f, ANNA)
    lines = [("them", "omg u like laufey too??"), ("her", "ur so annoying"), ("other", "anna is mean")]
    out = f.appraise(
        NS(id=ANNA),
        d,
        [
            {"kind": "shared_interest", "intensity": 2, "evidence": "u like laufey too", "why": "loves laufey too"},
            {"kind": "insulted_her", "intensity": 2, "evidence": "ur so annoying", "why": "called you annoying"},
            {"kind": "insulted_her", "intensity": 2, "evidence": "she said u suck", "why": "made up"},
            {"kind": "not_a_kind", "intensity": 2, "evidence": "omg", "why": "?"},
        ],
        lines,
    )
    assert d["regard"]["like"] > 0 and d["regard"]["hurt"] == 0
    assert any("shared interest" in line for line in out) and any("not backed by" in line for line in out)


def test_only_messages_said_to_her_count_and_friends_only_for_going_after_her_friends(make):
    f = make()
    d = person(f, ANNA)
    lines = [
        ("them_else", "ur so annoying bob"),
        ("them_friend", "shut up sam nobody likes you"),
        ("them_else", "shut up kevin nobody asked"),
        ("them", "u have such good taste in music"),
    ]
    out = f.appraise(
        NS(id=ANNA),
        d,
        [
            {"kind": "insulted_her", "intensity": 3, "evidence": "ur so annoying bob", "why": "x"},
            {"kind": "mean_to_her_friends", "intensity": 2, "evidence": "shut up kevin nobody asked", "why": "x"},
            {"kind": "mean_to_her_friends", "intensity": 2, "evidence": "shut up sam nobody likes you", "why": "x"},
            {"kind": "insulted_her", "intensity": 2, "evidence": "shut up sam nobody likes you", "why": "x"},
            {"kind": "compliment_her", "intensity": 1, "evidence": "u have such good taste", "why": "praised you"},
        ],
        lines,
    )
    kinds = [e["kind"] for e in d["regard"]["events"]]
    assert kinds == ["mean_to_her_friends", "compliment_her"]
    assert any("not backed by" in line and "insulted_her" in line for line in out)
    assert "mean_to_others" not in fe.KINDS


def test_a_message_not_said_to_her_never_stings(make):
    f = make()
    d = person(f, ANNA)
    f.heard(NS(author=NS(id=ANNA, display_name="anna"), content="ur so annoying stfu"), aimed=False)
    assert f.regard(d)["hurt"] == 0 and f.mood.level("irritated") == 0


def test_a_gut_reaction_then_the_judgment_doesnt_count_the_same_insult_twice(make):
    f = make()
    d = person(f, ANNA)
    f.heard(NS(author=NS(id=ANNA, display_name="anna"), content="ur so annoying stfu"))
    gut = d["regard"]["hurt"]
    assert gut >= 8
    f.appraise(
        NS(id=ANNA),
        d,
        [{"kind": "insulted_her", "intensity": 1, "evidence": "ur so annoying stfu", "why": "called you annoying"}],
        [("them", "ur so annoying stfu")],
    )
    assert d["regard"]["hurt"] < gut + fe.KINDS["insulted_her"][1]["hurt"] * 1.5


def test_banter_and_apologies_take_the_edge_off(make):
    f = make()
    d = person(f, ANNA)
    f.heard(NS(author=NS(id=ANNA, display_name="anna"), content="ur so dumb lmao 💀"))
    assert d["regard"]["hurt"] < 8
    f.heard(NS(author=NS(id=ANNA, display_name="anna"), content="ur so annoying stfu"))
    before = d["regard"]["hurt"]
    f.heard(NS(author=NS(id=ANNA, display_name="anna"), content="sorry i didnt mean that"))
    assert d["regard"]["hurt"] < before


@pytest.mark.parametrize(
    ("like", "says", "guard"),
    [
        (80, "You adore anna", False),
        (45, "You really like anna", False),
        (0, "don't have strong feelings", False),
        (-40, "You don't like anna", True),
        (-80, "can't stand anna", True),
    ],
)
def test_how_she_feels_is_told_to_her_with_guardrails_when_its_negative(make, like, says, guard):
    f = make()
    d = person(f, ANNA)
    f.regard(d)["like"] = like
    note = f.regard_note(NS(id=ANNA), d, "anna")
    assert says in note and (fe.DECENT in note) is guard


def test_hurt_and_chemistry_show_up_in_how_she_feels(make):
    f = make()
    d = person(f, ANNA)
    r = f.regard(d)
    r.update(like=40, spark=45, hurt=30, hurt_t=time.time(), hurt_why="called you annoying")
    note = f.regard_note(NS(id=ANNA), d, "anna")
    assert "flirt back" in note and "still upset with them (called you annoying" in note and fe.DECENT in note


def test_mood_fades_and_only_strong_feelings_show():
    m = Mood()
    m.feel("happy", 0.5, "anna hyped your clip", now=NOW)
    assert "pretty happy (anna hyped your clip)" in m.note(NOW)
    assert m.note(NOW + 8 * 3600) == ""
    m.feel("amused", 0.1, now=NOW)
    assert "amused" not in m.note(NOW)


def test_good_things_ease_a_bad_mood():
    m = Mood()
    m.feel("irritated", 0.5, "someone was rude", now=NOW)
    m.feel("happy", 0.5, "anna was sweet", now=NOW)
    assert m.level("irritated", NOW) < 0.5


def test_moods_have_a_baseline_from_her_day():
    m = Mood(baseline=lambda name, now: 0.3 if name == "stressed" else 0.0)
    assert m.level("stressed", NOW) == pytest.approx(0.3)
    m.feel("stressed", 0.4, now=NOW)
    assert m.level("stressed", NOW + 48 * 3600) == pytest.approx(0.3, abs=0.01)


def test_she_leaves_people_she_cant_stand_on_read_sometimes_but_never_her_owner(make, monkeypatch):
    f = make(LEAVE_ON_READ=1.0)
    monkeypatch.setattr(fe.random, "random", lambda: 0.0)
    f.regard(person(f, ANNA))["like"] = -90
    f.regard(person(f, OWNER))["like"] = -90
    assert f.leaves_on_read(NS(id=ANNA))
    assert not f.leaves_on_read(NS(id=ANNA), "comfort")
    assert not f.leaves_on_read(NS(id=OWNER))
    f.regard(person(f, ANNA))["like"] = 10
    assert not f.leaves_on_read(NS(id=ANNA))


def test_who_she_chimes_in_with_and_dms_follows_how_she_feels(make):
    f = make()
    f.regard(person(f, ANNA))["like"] = 50
    assert f.chime_factor(NS(id=ANNA)) > 1 and f.close_enough_to_dm(NS(id=ANNA))
    f.regard(person(f, ANNA))["like"] = -40
    assert f.chime_factor(NS(id=ANNA)) < 1 and not f.close_enough_to_dm(NS(id=ANNA))


def test_turned_off_means_everyone_gets_treated_the_same(make):
    f = make(FEELINGS=False)
    d = person(f, ANNA)
    assert f.apply(NS(id=ANNA), d, "insulted_her", 3, "x") == ""
    assert f.regard_note(NS(id=ANNA), d, "anna") == "" and f.chime_factor(NS(id=ANNA)) == 1.0


def test_tiers_cover_the_whole_range():
    assert [tier(v) for v in (100, 50, 20, 0, -10, -40, -100)] == [
        "adore",
        "really like",
        "like",
        "neutral",
        "wary",
        "dislike",
        "can't stand",
    ]
