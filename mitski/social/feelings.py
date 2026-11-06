"""Her feelings: how she feels about each person (like, trust, chemistry, hurt) and her own mood.

How much she likes someone changes the way a person's would: slowly, from what they actually do. Her memory-notes
model reads the chat and says what happened ("they made her laugh", "they called her dumb"), quoting the message;
the numbers are decided here, with the usual human biases: bad moments weigh more than good ones, the same
compliment wears off, friends' roasts sting less, sweet talk from someone she doesn't trust counts for less, and
nobody can flatter or bully their way up or down in a day. Hurt fades over hours, a real apology helps, and people
she stops talking to slowly drift back to neutral.

Her mood is a handful of emotions that rise with what happens (people, her day, the time) and fade back to a
baseline at their own pace. Only the strongest one or two ever show, and gently.
"""

import asyncio
import datetime as dt
import random
import re
import time

from mitski.core import logs
from mitski.core.component import Component
from mitski.core.storage import JsonFile
from mitski.core.text import cut, squash
from mitski.memory.dates import said_ago
from mitski.memory.heuristics import find_evidence

log = logs.get("feelings")

DAY = 86400
DIMS = ("like", "trust", "spark", "hurt")
BOUNDS = {"like": (-100.0, 100.0), "trust": (0.0, 100.0), "spark": (0.0, 100.0), "hurt": (0.0, 100.0)}
START = {"like": 0.0, "trust": 15.0, "spark": 0.0, "hurt": 0.0}
INTENSITY = {1: 1.0, 2: 1.8, 3: 2.6}
OWNER_FLOOR = {"like": 20.0, "trust": 50.0}
CLOSE = 35
FRIENDLY_ENOUGH_TO_DM = 25
EVENTS_KEPT = 40
DRIFT_AFTER_DAYS = 30
SPARK_FADES_AFTER_DAYS = 14

# kind -> (what it means, for the notes model; effect on like/trust/spark/hurt; effect on her mood)
KINDS = {
    "compliment_her": (
        "said something nice about her (her looks, her taste, something she did)",
        {"like": 2, "spark": 0.5, "hurt": -3},
        {"happy": 0.15},
    ),
    "kindness": ("was genuinely kind or sweet to her", {"like": 2, "trust": 1}, {"happy": 0.12, "content": 0.1}),
    "cares_about_her": (
        "checked on her or asked how she's doing and actually cared about the answer",
        {"like": 3, "trust": 2},
        {"affectionate": 0.15, "happy": 0.1},
    ),
    "supported_her": (
        "had her back, comforted her, or stood up for her",
        {"like": 4, "trust": 3, "hurt": -5},
        {"affectionate": 0.2, "content": 0.15},
    ),
    "apologized": (
        "sincerely apologized to her for something",
        {"like": 1, "trust": 1, "hurt": -15},
        {"irritated": -0.15, "sad": -0.1},
    ),
    "thanked_her": ("thanked her and meant it", {"like": 1}, {"happy": 0.06}),
    "shared_interest": (
        "turned out to like the same things she does (games, music, anime, shows, food, anything)",
        {"like": 3, "spark": 0.5},
        {"excited": 0.18, "happy": 0.1},
    ),
    "opened_up": (
        "shared something personal with her, trusting her with it",
        {"like": 2, "trust": 3},
        {"affectionate": 0.12},
    ),
    "made_her_laugh": ("made her laugh for real", {"like": 2, "spark": 0.5}, {"amused": 0.3, "happy": 0.08}),
    "fun_time": (
        "a fun back and forth, hanging out or playing together",
        {"like": 2},
        {"happy": 0.12, "content": 0.08},
    ),
    "remembered_her": (
        "remembered something she told them or something about her life",
        {"like": 2, "trust": 1},
        {"happy": 0.12, "affectionate": 0.08},
    ),
    "kept_promise": ("did what they said they would", {"like": 1, "trust": 3}, {"content": 0.08}),
    "invited_her": ("invited her to play, hop in vc or hang out", {"like": 2}, {"happy": 0.12, "excited": 0.08}),
    "flirted_nicely": (
        "flirted with her in a way she's into (respectful, playful, and she played along)",
        {"like": 1, "spark": 3},
        {"flustered": 0.2, "happy": 0.08},
    ),
    "genuine_affection": (
        "showed real, earned affection (not over the top, not to get something)",
        {"like": 3, "spark": 1, "hurt": -3},
        {"affectionate": 0.2, "happy": 0.1},
    ),
    "friendly_teasing": (
        "playful banter or a roast both of them clearly enjoyed",
        {"like": 1},
        {"amused": 0.15},
    ),
    "respectful_disagreement": (
        "disagreed with her but stayed respectful about it",
        {"trust": 1},
        {},
    ),
    "insulted_her": (
        "called her names or put her down, meaning it (not banter)",
        {"like": -4, "trust": -1, "hurt": 15},
        {"irritated": 0.25, "sad": 0.12},
    ),
    "mocked_her": (
        "made fun of her in a mean way, or embarrassed her in front of others",
        {"like": -4, "trust": -2, "hurt": 12},
        {"embarrassed": 0.2, "irritated": 0.2},
    ),
    "rude_to_her": (
        "was rude, cold or dismissive to her, or told her to shut up and meant it",
        {"like": -2, "hurt": 6},
        {"irritated": 0.15},
    ),
    "fake_affection": (
        "sweet talk that isn't real: love-bombing, buttering her up to get something, transactional",
        {"like": -1, "trust": -4, "spark": -2},
        {"irritated": 0.08},
    ),
    "pushy": (
        "romantic or sexual pushiness, didn't take no for an answer, or made her uncomfortable",
        {"like": -6, "trust": -5, "spark": -10, "hurt": 10},
        {"irritated": 0.3},
    ),
    "lied_to_her": ("lied to her and she knows it", {"like": -2, "trust": -6, "hurt": 5}, {"sad": 0.1}),
    "broke_promise": ("didn't do what they promised her", {"like": -1, "trust": -4, "hurt": 4}, {"sad": 0.08}),
    "trashed_her_likes": (
        "was a jerk about things she loves (not just a different taste)",
        {"like": -1, "hurt": 2},
        {"irritated": 0.08},
    ),
    "mean_to_her_friends": (
        "went after someone she's close to (only a message marked as said to that friend)",
        {"like": -5, "trust": -2, "hurt": 6},
        {"irritated": 0.2},
    ),
    "trolling_her": (
        "deliberately tried to provoke her, mess with her or waste her time",
        {"like": -2, "trust": -2, "hurt": 4},
        {"irritated": 0.15},
    ),
    "threatened_her": ("threatened her", {"like": -10, "trust": -10, "hurt": 20}, {"irritated": 0.3, "sad": 0.2}),
}
NEGATIVE = {k for k, (_, fx, _) in KINDS.items() if fx.get("like", 0) < 0 or fx.get("hurt", 0) > 0}
SEEN_FROM_FRIENDS_LIGHTLY = {"insulted_her", "mocked_her", "rude_to_her", "trolling_her"}
SKEPTICAL = {"compliment_her", "kindness", "genuine_affection", "flirted_nicely", "fake_affection"}

TIERS = (
    (65, "adore"),
    (35, "really like"),
    (12, "like"),
    (-8, "neutral"),
    (-25, "wary"),
    (-60, "dislike"),
    (-101, "can't stand"),
)
TIER_NOTES = {
    "adore": "You adore {call}: you're openly warm and affectionate with them, you hype them up, you're protective "
    "of them and happy whenever they show up.",
    "really like": "You really like {call}: you're warm and playful with them, you tease them because you're "
    "comfortable, and you care how they're doing.",
    "like": "You like {call}: friendly, easy-going and glad to chat.",
    "neutral": "You don't have strong feelings about {call} either way yet: casual and friendly, but you don't go "
    "out of your way for them.",
    "wary": "You're a bit wary of {call}: less warm than usual, shorter replies, a little sarcastic, and no flirting.",
    "dislike": "You don't like {call}: you're cool and curt with them, sarcastic, you don't do them favours, and you "
    "call out their nonsense.",
    "can't stand": "You really can't stand {call}: you're openly cold and dismissive, you'd rather not talk to them, "
    "and you shut them down if they start something.",
}
DECENT = (
    "Being cold never means slurs, threats or going after their looks, race, gender, sexuality or disabilities, "
    "and if they're genuinely going through something serious, you drop the attitude and are decent."
)

# her mood: emotion -> (minutes to fade halfway back to baseline, how it reads)
EMOTIONS = {
    "happy": (180, "happy"),
    "amused": (30, "amused"),
    "excited": (90, "excited"),
    "affectionate": (240, "soft and affectionate"),
    "flustered": (40, "flustered"),
    "proud": (240, "proud of yourself"),
    "content": (300, "content and chill"),
    "sad": (360, "down"),
    "lonely": (240, "lonely"),
    "irritated": (120, "irritated"),
    "stressed": (480, "stressed"),
    "embarrassed": (45, "embarrassed"),
    "bored": (90, "bored"),
    "tired": (300, "tired"),
}
GOOD = {"happy", "amused", "excited", "affectionate", "flustered", "proud", "content"}
BAD = {"sad", "lonely", "irritated", "stressed", "embarrassed", "bored"}
SHOWS_AT = 0.22
DAY_MOODS = (
    ({}, 5),
    ({"happy": 0.15}, 2),
    ({"content": 0.15}, 2),
    ({"tired": 0.15}, 1),
    ({"irritated": 0.1}, 1),
    ({"bored": 0.12}, 1),
    ({"sad": 0.1}, 1),
)
LONELY_AFTER_SEC = 3 * 3600
TICK_SEC = 300

INSULT = re.compile(
    r"\b(stfu|shut up|stupid|dumb(ass)?|idiot|moron|ugly|annoying|loser|cringe|trash|garbage|bitch|whore|slut|"
    r"useless|pathetic|clown|nobody likes (you|u)|(hate|hating) (you|u)|fuck (you|u|off)|ur (so )?(dumb|stupid|"
    r"annoying|useless|trash|cringe|ugly|boring|weird|mid))\b",
    re.I,
)
SEVERE = re.compile(r"\b(kys|kill (yo)?urself|go die|i('ll| will) (kill|hurt|find) (you|u))\b", re.I)
COMPLIMENT = re.compile(
    r"\b(ur|you'?re|youre|u r|you are) (so |really |actually |literally )?(cute|pretty|funny|sweet|smart|cool|"
    r"the best|goated|amazing|awesome|adorable|gorgeous|beautiful|talented|nice)\b|\b(love (you|u)|ily|i missed "
    r"(you|u)|miss (you|u)|queen|goat(ed)?)\b|❤|🥰|😍|💕",
    re.I,
)
THANKS = re.compile(r"\b(ty|tysm|thx|thanks|thank (you|u))\b", re.I)
SORRY = re.compile(r"\b(sorry|sry|my bad|i apologi[sz]e|didn'?t mean (it|that))\b", re.I)
BANTER = re.compile(r"\b(lol|lmao|lmfao|haha\w*|jk|/j|xd)\b|😭|💀|😂|🤣", re.I)


def tier(like):
    return next(name for floor, name in TIERS if like >= floor)


def intensity_of(raw):
    try:
        return min(max(int(raw), 1), 3)
    except (TypeError, ValueError):
        return 1


def fresh_regard(d=None):
    """Someone new is neutral with a little trust. People from before the overhaul start from their old vibe."""
    r = dict(START, hurt_t=0.0, hurt_why="", events=[], day="", day_like=0.0, pending_hurt=0.0)
    if d is not None and "vibe" in d:
        r["like"] = max(-30.0, min(30.0, float(d.pop("vibe") or 0) * 6))
        r["trust"] = min(40.0, START["trust"] + d.get("talks", 0) / 20)
    return r


def hurt_now(r, now, half_life_hours):
    if r["hurt"] <= 0 or half_life_hours <= 0:
        return 0.0
    hours = max(0.0, now - r.get("hurt_t", now)) / 3600
    return r["hurt"] * 0.5 ** (hours / half_life_hours)


def drifted(r, last_seen, now):
    """People she hasn't talked to in a month slowly fade back towards neutral, and chemistry fades sooner."""
    days = max(0.0, now - (last_seen or now)) / DAY
    like, spark = r["like"], r["spark"]
    if days > DRIFT_AFTER_DAYS:
        like *= 0.99 ** (days - DRIFT_AFTER_DAYS)
    if days > SPARK_FADES_AFTER_DAYS:
        spark *= 0.98 ** (days - SPARK_FADES_AFTER_DAYS)
    return like, spark


def recent_count(r, kind, now, hours=24):
    return sum(1 for e in r.get("events", []) if e.get("kind") == kind and now - e.get("t", 0) < hours * 3600)


def effects(kind, intensity, r, now, *, speed=1.0, minor=False, early=False):
    """What one moment does to how she feels about someone, before it's added on. All the human biases live here."""
    base = KINDS[kind][1]
    scale = INTENSITY[intensity_of(intensity)]
    seen = recent_count(r, kind, now)
    if kind in NEGATIVE:
        scale *= 1.5 * 0.85**seen
    else:
        scale *= 0.6**seen
    out = {dim: v * scale for dim, v in base.items()}
    if kind in SEEN_FROM_FRIENDS_LIGHTLY and r["like"] >= CLOSE and r["trust"] >= 40:
        out = {dim: v * 0.5 for dim, v in out.items()}
    if kind in SKEPTICAL and r["like"] < -25:
        out = {dim: (v * 0.6 if v > 0 else v) for dim, v in out.items()}
    if kind in ("genuine_affection", "flirted_nicely") and (early or r["trust"] < 30):
        out = {dim: (v * 0.4 if v > 0 else v) for dim, v in out.items()}
        out["trust"] = out.get("trust", 0) - (1 if early and intensity_of(intensity) >= 3 else 0)
    if kind == "apologized" and recent_count(r, "apologized", now, 72) >= 2:
        out = {dim: v * 0.4 for dim, v in out.items()}
    for dim in ("like", "trust", "spark"):
        if dim in out:
            out[dim] *= speed
    if minor:
        out.pop("spark", None)
    return out


def add(r, dim, delta):
    """Moving further towards an extreme gets harder, moving back towards neutral doesn't."""
    low, high = BOUNDS[dim]
    value = r[dim]
    if dim == "like" and delta * value > 0:
        delta *= max(0.1, 1 - abs(value) / 110)
    r[dim] = round(max(low, min(high, value + delta)), 2)
    return r[dim] - value


def mood_word(v):
    return "really" if v >= 0.6 else "pretty" if v >= 0.38 else "a little"


class Mood:
    """Her emotions right now. Each one fades back to its baseline (from her day) at its own speed."""

    def __init__(self, data=None, baseline=None):
        data = data if isinstance(data, dict) else {}
        self.felt = {k: v for k, v in (data.get("felt") or {}).items() if k in EMOTIONS and isinstance(v, dict)}
        self.last_contact = float(data.get("last_contact") or 0)
        self.baseline = baseline or (lambda name, now: 0.0)

    def to_json(self):
        return {"felt": self.felt, "last_contact": self.last_contact}

    def level(self, name, now=None):
        now = now or time.time()
        base = self.baseline(name, now)
        f = self.felt.get(name)
        if not f:
            return base
        minutes = max(0.0, now - f["t"]) / 60
        return max(0.0, min(1.0, base + (f["v"] - base) * 0.5 ** (minutes / EMOTIONS[name][0])))

    def feel(self, name, amount, why="", now=None):
        if name not in EMOTIONS or not amount:
            return
        now = now or time.time()
        value = max(0.0, min(1.0, self.level(name, now) + amount))
        self.felt[name] = {"v": round(value, 3), "t": now, "why": cut(squash(why), 90) if amount > 0 else ""}
        if amount > 0 and name in GOOD:
            for bad in BAD & set(self.felt):
                self._ease(bad, amount * 0.3, now)
        elif amount > 0 and name in BAD:
            for good in GOOD & set(self.felt):
                self._ease(good, amount * 0.2, now)

    def _ease(self, name, amount, now):
        value = max(0.0, self.level(name, now) - amount)
        self.felt[name] = {"v": round(value, 3), "t": now, "why": self.felt.get(name, {}).get("why", "")}

    def strongest(self, now=None, n=2):
        now = now or time.time()
        levels = sorted(((self.level(name, now), name) for name in EMOTIONS), reverse=True)
        return [(name, v) for v, name in levels[:n] if v >= SHOWS_AT]

    def note(self, now=None):
        top = self.strongest(now)
        if not top:
            return ""
        parts = []
        for name, v in top:
            why = self.felt.get(name, {}).get("why")
            parts.append(f"{mood_word(v)} {EMOTIONS[name][1]}" + (f" ({why})" if why else ""))
        return (
            f"How you feel right now: {' and '.join(parts)}. Let it colour how you talk a little (shorter and flatter "
            f"when you're down, irritated or tired, more playful and chatty when you're happy), but don't announce "
            f"it unless someone asks how you are, and don't take it out on people who didn't cause it."
        )


class Feelings(Component):
    def __init__(self, app):
        super().__init__(app)
        self.file = JsonFile(app.cfg.paths.data_file("mood.json"))
        self.mood = Mood(baseline=self._baseline)
        self.dirty = False

    @property
    def people_on(self):
        return bool(self.cfg.FEELINGS)

    @property
    def mood_on(self):
        return bool(self.cfg.MOOD)

    def load(self):
        self.mood = Mood(self.file.load(), baseline=self._baseline)

    def save_if_dirty(self):
        if self.dirty:
            self.file.save(self.mood.to_json())
            self.dirty = False

    # ---- how she feels about people ----

    def regard(self, d):
        if "regard" not in d or not isinstance(d["regard"], dict):
            d["regard"] = fresh_regard(d)
        d.pop("vibe", None)
        r = d["regard"]
        for key, value in fresh_regard().items():
            r.setdefault(key, value)
        return r

    def view(self, d, user_id=None, now=None):
        """How she feels about someone right now: drift, fading hurt and her owner's floor taken into account."""
        now = now or time.time()
        r = self.regard(d)
        like, spark = drifted(r, d.get("last_seen"), now)
        out = {"like": like, "trust": r["trust"], "spark": spark, "hurt": hurt_now(r, now, self.cfg.GRUDGE_HOURS)}
        if user_id is not None and self.app.owner.is_owner(user_id):
            for dim, floor in OWNER_FLOOR.items():
                out[dim] = max(out[dim], floor)
        return out

    def settle(self, d, now=None):
        """Makes drift and faded hurt permanent, right before someone talks to her again after a while."""
        now = now or time.time()
        r = self.regard(d)
        r["like"], r["spark"] = (round(v, 2) for v in drifted(r, d.get("last_seen"), now))
        r["hurt"], r["hurt_t"] = round(hurt_now(r, now, self.cfg.GRUDGE_HOURS), 2), now

    def like_of(self, user):
        d = self._person(user)
        return self.view(d, user.id)["like"] if d is not None else 0.0

    def _person(self, user):
        if not self.people_on or user is None or getattr(user, "id", None) is None:
            return None
        return self.memory.get(user.id)

    def _minor(self, user, d):
        age = self.memory.current_age(d) if d is not None else None
        return (age is not None and age < 18) or (user is not None and self.app.ages.is_minor(user))

    def apply(self, user, d, kind, intensity=1, why="", src="notes", now=None):
        """Adds one moment to how she feels about someone. Returns a line for the log, or "" if nothing moved."""
        if not self.people_on or kind not in KINDS:
            return ""
        now = now or time.time()
        self.settle(d, now)
        r = self.regard(d)
        early = d.get("talks", 0) < 20
        fx = effects(kind, intensity, r, now, speed=float(self.cfg.LIKE_SPEED), minor=self._minor(user, d), early=early)
        moved = {}
        day = dt.date.fromtimestamp(now).isoformat()
        if r.get("day") != day:
            r["day"], r["day_like"] = day, 0.0
        for dim, delta in fx.items():
            if dim == "hurt" and delta > 0:
                delta = max(0.0, delta - r.get("pending_hurt", 0.0))
                r["pending_hurt"] = 0.0
            if dim == "like":
                room = float(self.cfg.LIKE_DAILY_MAX)
                delta = max(-room - r["day_like"], min(room - r["day_like"], delta))
                r["day_like"] += delta
            if abs(delta) < 0.01:
                continue
            moved[dim] = round(add(r, dim, delta), 2)
            if dim == "hurt" and moved[dim] > 0:
                r["hurt_t"], r["hurt_why"] = now, cut(squash(why) or KINDS[kind][0], 100)
        if user is not None and self.app.owner.is_owner(user):
            for dim, floor in OWNER_FLOOR.items():
                r[dim] = max(r[dim], floor)
        call = self.memory.call_name(d) or d.get("name") or "someone"
        for emotion, amount in KINDS[kind][2].items():
            self.feel(emotion, amount * (1 + max(0.0, r["like"]) / 200 if amount > 0 else 1), f"{call} {why}")
        moved = {k: v for k, v in moved.items() if abs(v) >= 0.01}
        if not moved:
            return ""
        r["events"] = (
            r.get("events", [])
            + [
                {
                    "t": now,
                    "kind": kind,
                    "i": intensity_of(intensity),
                    "d": moved,
                    "why": cut(squash(why), 100),
                    "src": src,
                }
            ]
        )[-EVENTS_KEPT:]
        return (
            f"♡ {kind.replace('_', ' ')}"
            + (f" ({cut(why, 60)})" if why else "")
            + ": "
            + ", ".join(f"{dim} {v:+g}" for dim, v in moved.items())
        )

    def appraise(self, user, d, items, lines):
        """The memory-notes model's read on how they treated her. Every moment has to quote one of their own
        messages that was really said TO her ("them" in lines). The only exception is going after someone she's
        close to, which has to quote a message said to that friend ("them_friend"). Messages to anyone else, or to
        the room, never count: the code checks who each message was for, it doesn't take the model's word."""
        if not self.people_on or not items:
            return []
        changes, dropped = [], []
        for item in items[:5]:
            if not isinstance(item, dict) or item.get("kind") not in KINDS:
                continue
            quote = item.get("evidence")
            needed = "them_friend" if item["kind"] == "mean_to_her_friends" else "them"
            if not quote or find_evidence(quote, lines) != needed:
                dropped.append(item.get("kind"))
                continue
            why = cut(squash(item.get("why")), 100)
            line = self.apply(user, d, item["kind"], item.get("intensity"), why)
            if line:
                changes.append(line)
        if dropped:
            changes.append("✗ feelings not backed by a message said to her, ignored: " + ", ".join(map(str, dropped)))
        return changes

    def heard(self, msg, aimed=True):
        """Someone just said something to her. A quick gut reaction: her mood, and how hurt she is, nothing more.
        The real judgment of how they treated her comes later, from her memory notes. Only a message that was
        really said TO her (aimed) can sting or flatter her: one she's just chiming in on is about someone else."""
        text = msg.content or ""
        now = time.time()
        self.mood.last_contact = now
        self.mood.feel("lonely", -0.15, now=now)
        self.mood.feel("bored", -0.1, now=now)
        self.dirty = True
        if not aimed:
            return
        d = self._person(msg.author)
        r = self.regard(d) if d is not None else None
        if d is not None:
            self.settle(d, now)
        close = r is not None and r["like"] >= CLOSE
        playful = bool(BANTER.search(text))
        call = (self.memory.call_name(d) if d else None) or getattr(msg.author, "display_name", "someone")
        if SEVERE.search(text):
            self._sting(r, 20, f"{call} said something really nasty to you", now)
            self.feel("irritated", 0.35, f"{call} said something nasty")
            self.feel("sad", 0.2, f"{call} said something nasty")
        elif INSULT.search(text):
            soft = 0.4 if playful or close else 1.0
            self._sting(r, 10 * soft, f'{call} said "{cut(squash(text), 60)}"', now)
            self.feel("irritated", 0.25 * soft, f"{call} was rude to you")
        elif COMPLIMENT.search(text):
            self.feel("happy", 0.12, f"{call} was sweet to you")
            if r is not None and r["spark"] >= 30 and not self._minor(msg.author, d):
                self.feel("flustered", 0.12, f"{call} was sweet to you")
            if r is not None and r["hurt"] > 0:
                r["hurt"] = max(0.0, r["hurt"] - 2)
        if THANKS.search(text):
            self.feel("happy", 0.05, f"{call} thanked you")
        if SORRY.search(text) and r is not None and hurt_now(r, now, self.cfg.GRUDGE_HOURS) > 0:
            r["hurt"], r["hurt_t"] = round(hurt_now(r, now, self.cfg.GRUDGE_HOURS) * 0.7, 2), now
            self.feel("irritated", -0.1)

    def _sting(self, r, amount, why, now):
        if r is None or not self.people_on:
            return
        r["hurt"] = round(min(100.0, hurt_now(r, now, self.cfg.GRUDGE_HOURS) + amount), 2)
        r["hurt_t"], r["hurt_why"] = now, cut(why, 100)
        r["pending_hurt"] = round(r.get("pending_hurt", 0.0) + amount, 2)

    def regard_note(self, user, d, call):
        """What she's told about how she feels about the person she's talking to."""
        if not self.people_on or d is None:
            return ""
        now = time.time()
        v = self.view(d, getattr(user, "id", None), now)
        r = self.regard(d)
        minor = self._minor(user, d)
        level = tier(v["like"])
        out = [TIER_NOTES[level].format(call=call)]
        if v["trust"] >= 70:
            out.append("You trust them a lot, you can be open and real with them.")
        elif v["trust"] < 20 and v["like"] >= 12:
            out.append("You don't fully trust them yet, so you keep the personal stuff to yourself.")
        if minor:
            out.append("They're a minor: no flirting or anything romantic, ever.")
        elif v["like"] >= 12 and v["spark"] >= 60:
            out.append("There's real chemistry: you get flirty and a little flustered around them.")
        elif v["like"] >= 12 and v["spark"] >= 30:
            out.append("There's a bit of chemistry, so you flirt back when they flirt.")
        if v["hurt"] >= 8:
            how = (
                "really hurt and upset with them"
                if v["hurt"] >= 50
                else "still upset with them"
                if v["hurt"] >= 25
                else "still a little annoyed with them"
            )
            why = r.get("hurt_why") or "something they did"
            out.append(
                f"You're {how} ({why}, {said_ago(r.get('hurt_t', now), now)}): you're cooler with them until they "
                f"make it right, and if they apologize and mean it, you soften."
            )
        lately = [
            e for e in r.get("events", [])[-6:] if now - e["t"] < 14 * DAY and e.get("why") and e.get("src") != "hand"
        ][-2:]
        if lately:
            out.append("Lately: " + "; ".join(f"they {e['why'].rstrip('.')}" for e in lately) + ".")
        if level in ("wary", "dislike", "can't stand") or v["hurt"] >= 25:
            out.append(DECENT)
        return " ".join(out)

    def stands_out(self, d, user_id=None):
        """Worth mentioning even about someone she's only just met: they already hurt her, or she already likes or
        dislikes them."""
        if not self.people_on or d is None:
            return False
        v = self.view(d, user_id)
        return v["hurt"] >= 8 or tier(v["like"]) != "neutral"

    def summary(self, d, user_id=None):
        if not self.people_on or d is None:
            return ""
        v = self.view(d, user_id)
        trust = "a lot" if v["trust"] >= 70 else "somewhat" if v["trust"] >= 35 else "not much yet"
        return f"you {tier(v['like']).replace('neutral', 'feel neutral about')} them and trust them {trust}"

    # ---- what her feelings change about what she does ----

    def leaves_on_read(self, user, reply_type=""):
        """People she really doesn't like sometimes get left on read for small talk."""
        if not self.people_on or self.app.owner.is_owner(user) or reply_type in ("comfort", "help"):
            return False
        like = self.like_of(user)
        if like > -30:
            return False
        return random.random() < float(self.cfg.LEAVE_ON_READ) * min(1.0, (-like - 20) / 60)

    def chime_factor(self, user):
        if not self.people_on:
            return 1.0
        like = self.like_of(user)
        return 1.4 if like >= CLOSE else 1.15 if like >= 12 else 0.3 if like <= -25 else 1.0

    def close_enough_to_dm(self, user):
        return not self.people_on or self.app.owner.is_owner(user) or self.like_of(user) >= FRIENDLY_ENOUGH_TO_DM

    # ---- her mood ----

    def feel(self, name, amount, why=""):
        if self.mood_on and amount:
            self.mood.feel(name, amount * (float(self.cfg.MOOD_SWING) if amount > 0 else 1.0), why)
            self.dirty = True

    def mood_note(self):
        return self.mood.note() if self.mood_on else ""

    def _baseline(self, name, now):
        if not self.mood_on:
            return 0.0
        when = dt.datetime.fromtimestamp(now, getattr(self.app.clock.now(), "tzinfo", None))
        base = self._day_mood(when.date()).get(name, 0.0)
        routine = getattr(self.app, "routine", None)
        planner = getattr(routine, "planner", None)
        if planner is not None and planner.on:
            phase = (planner._store().get("term") or {}).get("phase")
            if name == "stressed" and phase == "exams":
                base += 0.25
            if name == "excited" and planner.trip_on(when.date()):
                base += 0.2
        if name == "tired" and (when.hour < 6 or when.hour >= 23):
            base += 0.3
        if name == "content" and when.weekday() >= 5:
            base += 0.08
        return min(base, 0.6)

    def _day_mood(self, day):
        rng = random.Random(f"{self.cfg.OWNER_ID}:mood:{day.isoformat()}")
        moods, weights = zip(*DAY_MOODS, strict=True)
        return rng.choices(moods, weights)[0]

    def tick(self, now=None):
        now = now or time.time()
        routine = getattr(self.app, "routine", None)
        awake_and_free = routine is None or routine.free
        if awake_and_free and self.mood.last_contact and now - self.mood.last_contact > LONELY_AFTER_SEC:
            self.mood.feel("lonely", 0.04, "nobody's talked to you in a while", now)
            self.mood.feel("bored", 0.03, "it's quiet", now)
            self.dirty = True

    def report(self):
        now = time.time()
        rows = [
            f"{name}: {self.mood.level(name, now):.2f}"
            + (f" (base {self._baseline(name, now):.2f})" if self._baseline(name, now) else "")
            + (f" · {self.mood.felt[name]['why']}" if self.mood.felt.get(name, {}).get("why") else "")
            for name in EMOTIONS
            if self.mood.level(name, now) >= 0.05
        ]
        note = self.mood_note() or "nothing strong right now, she's in a normal mood"
        return "**her mood**\n" + ("\n".join(rows) or "all calm") + f"\n-# {note}"

    def describe_person(self, d, user_id=None):
        v = self.view(d, user_id)
        r = self.regard(d)
        head = (
            f"**{d.get('name', '?')}** · {tier(v['like'])} · like {v['like']:.0f} · trust {v['trust']:.0f} · "
            f"chemistry {v['spark']:.0f} · hurt {v['hurt']:.0f}"
            + (f" ({r.get('hurt_why')})" if v["hurt"] >= 1 and r.get("hurt_why") else "")
        )
        events = [
            f"{said_ago(e['t'], time.time())}: {e['kind'].replace('_', ' ')}"
            + (f" ({e['why']})" if e.get("why") else "")
            + " → "
            + ", ".join(f"{k} {val:+g}" for k, val in e["d"].items())
            for e in r.get("events", [])[-10:]
        ]
        return head + ("\n" + "\n".join(events) if events else "\n(nothing yet)")

    async def run(self):
        while True:
            await asyncio.sleep(TICK_SEC)
            try:
                self.tick()
                self.save_if_dirty()
            except Exception:
                log.warning("feelings tick failed", exc_info=True)
