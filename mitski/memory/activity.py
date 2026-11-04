import time

from mitski.core.clock import DAY, ago

SESSION_CAP_MIN = 12 * 60
REJOIN_SEC = 15 * 60
TRACK_REPEAT_SEC = 20 * 60
KEEP_DAYS = 45
MAX_GAMES, MAX_ARTISTS, MAX_TRACKS, MAX_WATCHING, MAX_STATUSES = 25, 40, 20, 12, 6


def day_of(t):
    return int(t // DAY)


def empty():
    return {"games": {}, "artists": {}, "tracks": [], "watching": {}, "statuses": []}


def migrate(d):
    act = d.setdefault("activity", empty())
    for k, v in empty().items():
        act.setdefault(k, v)
    old = d.pop("habits", None) or {}
    last = d.get("last_seen", time.time())
    first = min(d.get("first_seen", last), last - 30 * DAY)
    for name, n in (old.get("games") or {}).items():
        act["games"].setdefault(name, {"n": int(n), "min": 0, "first": first, "last": last, "days": {}})
    for name, n in (old.get("music") or {}).items():
        act["artists"].setdefault(name, {"n": int(n), "first": first, "last": last, "days": {}})
    return act


def _bump_day(entry, t, amount):
    days = entry.setdefault("days", {})
    key = str(day_of(t))
    days[key] = round(days.get(key, 0) + amount, 1)
    cutoff = day_of(t) - KEEP_DAYS
    for k in [k for k in days if int(k) < cutoff]:
        del days[k]


def _recent(entry, now, days):
    cutoff = day_of(now) - days
    return sum(v for k, v in (entry.get("days") or {}).items() if int(k) > cutoff)


def _prune(store, limit, key):
    while len(store) > limit:
        del store[min(store, key=lambda k: key(store[k]))]


class Tracker:
    def __init__(self):
        self.open = {}
        self.closed = {}
        self.tracks = {}
        self.watching = {}

    def sync(self, d, uid, now_doing, t=None):
        t = t or time.time()
        act = migrate(d)
        events = []
        games = {x["name"] for x in now_doing if x.get("kind") == "game" and x.get("name")}
        for u, g in [k for k in self.open if k[0] == uid and k[1] not in games]:
            start = self.open.pop((u, g))
            minutes = min((t - start) / 60, SESSION_CAP_MIN)
            e = act["games"].get(g)
            if e is not None and minutes >= 1:
                e["min"] = round(e.get("min", 0) + minutes, 1)
                e["last"] = t
                _bump_day(e, t, minutes)
            self.closed[(u, g)] = t
        for g in games:
            if (uid, g) in self.open:
                continue
            self.open[(uid, g)] = t
            e = act["games"].setdefault(g, {"n": 0, "min": 0, "first": t, "last": t, "days": {}})
            if t - self.closed.get((uid, g), -1e12) > REJOIN_SEC:
                e["n"] += 1
                if e["n"] == 1:
                    events.append(f"first time playing {g}")
            e["last"] = t
        _prune(act["games"], MAX_GAMES, lambda e: (e.get("min", 0) + 30 * e.get("n", 0), e.get("last", 0)))

        for x in now_doing:
            kind = x.get("kind")
            if kind == "music" and x.get("artist"):
                key = (uid, x.get("track") or f"{x.get('title')}|{x['artist']}")
                if t - self.tracks.get(key, -1e12) < TRACK_REPEAT_SEC:
                    continue
                self.tracks[key] = t
                for artist in [a.strip() for a in str(x["artist"]).split(";") if a.strip()][:2]:
                    e = act["artists"].setdefault(artist, {"n": 0, "first": t, "last": t, "days": {}})
                    e["n"] += 1
                    e["last"] = t
                    _bump_day(e, t, 1)
                last = act["tracks"][-1] if act["tracks"] else None
                if not last or (last.get("title"), last.get("artist")) != (x.get("title"), x["artist"]):
                    act["tracks"].append({"title": x.get("title") or "", "artist": x["artist"], "t": t})
                    del act["tracks"][:-MAX_TRACKS]
            elif kind == "watching" and x.get("name"):
                key = (uid, x["name"])
                if t - self.watching.get(key, -1e12) < 3600:
                    continue
                self.watching[key] = t
                e = act["watching"].setdefault(x["name"], {"n": 0, "first": t, "last": t})
                e["n"] += 1
                e["last"] = t
            elif kind == "status" and x.get("text"):
                text = str(x["text"]).strip()[:100]
                if text and (not act["statuses"] or act["statuses"][-1]["text"] != text):
                    act["statuses"].append({"text": text, "t": t})
                    del act["statuses"][:-MAX_STATUSES]
        _prune(act["artists"], MAX_ARTISTS, lambda e: (e.get("n", 0), e.get("last", 0)))
        _prune(act["watching"], MAX_WATCHING, lambda e: (e.get("n", 0), e.get("last", 0)))
        return events

    def sweep(self, t=None):
        t = t or time.time()
        gone = 0
        for store, keep in ((self.closed, REJOIN_SEC), (self.tracks, TRACK_REPEAT_SEC), (self.watching, 3600)):
            stale = [k for k, seen in store.items() if t - seen > keep]
            for k in stale:
                del store[k]
            gone += len(stale)
        return gone

    def playing_for(self, uid, game, t=None):
        start = self.open.get((uid, game))
        return None if start is None else ((t or time.time()) - start) / 60


def hours(minutes):
    h = minutes / 60
    if h < 1:
        return f"{int(minutes)}min"
    return f"~{h:.0f}h" if h >= 10 else f"~{h:.1f}h".replace(".0h", "h")


def games_summary(act, now=None, n=4):
    now = now or time.time()
    games = act.get("games") or {}
    if not games:
        return ""
    real = {g: e for g, e in games.items() if e.get("n", 0) >= 2 or e.get("min", 0) >= 60}
    if not real:
        return ""
    total = sorted(real, key=lambda g: -(real[g].get("min", 0) + 20 * real[g].get("n", 0)))
    lately = sorted((g for g in real if _recent(real[g], now, 14) >= 30), key=lambda g: -_recent(real[g], now, 14))
    bits = []
    for g in total[:n]:
        e = real[g]
        info = []
        if e.get("min", 0) >= 30:
            info.append(hours(e["min"]) + " in total")
        week = _recent(e, now, 7)
        if week >= 60:
            info.append(f"{hours(week)} this week")
        if now - e.get("first", now) < 7 * DAY and e.get("n", 0) >= 2:
            info.append("new this week")
        elif now - e.get("last", now) > 30 * DAY:
            info.append(f"hasn't played it since {ago(e['last'], now)}")
        bits.append(g + (f" ({', '.join(info)})" if info else ""))
    out = "plays " + "; ".join(bits)
    new_lately = [g for g in lately[:2] if g not in total[:n]]
    if new_lately:
        out += ". Lately also a lot of " + " and ".join(new_lately)
    return out


def music_summary(act, now=None, n=5):
    now = now or time.time()
    artists = {a: e for a, e in (act.get("artists") or {}).items() if e.get("n", 0) >= 2}
    if not artists:
        return ""
    top = sorted(artists, key=lambda a: -artists[a]["n"])[:n]
    lately = sorted(
        (a for a in artists if _recent(artists[a], now, 7) >= 3), key=lambda a: -_recent(artists[a], now, 7)
    )
    out = "listens to " + ", ".join(top) + " on spotify"
    fresh = [a for a in lately[:2] if a not in top[:3]]
    if fresh:
        out += ", and lately a lot of " + " and ".join(fresh)
    tracks = act.get("tracks") or []
    if tracks and now - tracks[-1]["t"] < 3 * DAY:
        tr = tracks[-1]
        out += f'. Last song you saw them on: "{tr["title"]}" by {tr["artist"]} ({ago(tr["t"], now)})'
    return out


def watching_summary(act, now=None):
    now = now or time.time()
    w = {k: e for k, e in (act.get("watching") or {}).items() if e.get("n", 0) >= 2}
    if not w:
        return ""
    return "watches " + ", ".join(sorted(w, key=lambda k: -w[k]["n"])[:3])


def status_summary(act, now=None):
    now = now or time.time()
    st = [s for s in act.get("statuses") or [] if now - s["t"] < 10 * DAY]
    if not st:
        return ""
    return f'their status said "{st[-1]["text"]}" ({ago(st[-1]["t"], now)})'


def summary(d, now=None):
    act = d.get("activity")
    if not act:
        return ""
    parts = [
        p
        for p in (
            games_summary(act, now),
            music_summary(act, now),
            watching_summary(act, now),
            status_summary(act, now),
        )
        if p
    ]
    return ". ".join(p[0].upper() + p[1:] for p in parts)


def right_now(d, doing, tracker=None, uid=None, now=None):
    now = now or time.time()
    act = (d.get("activity") or {}) if d else {}
    out = []
    for x in doing:
        if x.get("kind") == "game" and x.get("name"):
            e = (act.get("games") or {}).get(x["name"])
            mins = tracker.playing_for(uid, x["name"], now) if tracker and uid is not None else None
            bits = [f"on it for {hours(mins)} now"] if mins and mins >= 20 else []
            if e:
                week = _recent(e, now, 7) + (mins or 0)
                if e.get("n", 0) <= 1 and e.get("min", 0) < 60:
                    bits.append("you've never seen them play it before")
                elif week >= 120:
                    bits.append(f"{hours(week)} this week")
                elif now - e.get("last", now) > 30 * DAY:
                    bits.append("first time in a while")
            if bits:
                out.append(f"{x['name']}: " + ", ".join(bits))
        elif x.get("kind") == "music" and x.get("artist"):
            artist = str(x["artist"]).split(";")[0].strip()
            e = (act.get("artists") or {}).get(artist)
            if e and e.get("n", 0) >= 10:
                out.append(f"{artist}: one of their favorite artists")
            elif e and e.get("n", 0) <= 1:
                out.append(f"{artist}: not something you've seen them listen to before")
    return out
