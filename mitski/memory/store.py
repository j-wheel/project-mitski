import asyncio
import contextlib
import datetime as dt
import math
import re
import time

from mitski.core import logs, voice
from mitski.core.text import cut
from mitski.memory import activity
from mitski.memory.dates import (
    DAY,
    birthday_in,
    birthdays_between,
    parse_birthday,
    parse_date,
    said_ago,
)
from mitski.memory.heuristics import (
    AGE_NOW,
    BEING_AI_OR_HUMAN,
    CALL_ME,
    DISCLOSURE,
    DONT_CALL,
    FIRST_PERSON,
    HER_NICK,
    MY_NAME,
    NON_ANSWER,
    PET_NAMES,
    clean_fact,
    clean_name,
    junk_fact,
    norm_cat,
    rank,
    similar,
    unsure,
)
from mitski.memory.schema import CATEGORIES, MONTHS, SLOTS

log = logs.get("memory")

VOICE_BACKUP = "memory.before-voice-fix.db"
NOTES_ABOUT_US = ("bond", "portrait", "talk_style", "history")
LISTS_ABOUT_US = (
    ("episodes", "summary"),
    ("threads", "text"),
    ("jokes", "text"),
    ("shared", "text"),
    ("avoid", "text"),
)


class PeopleStore:
    def load(self):
        self.people, self.own = self.db.load()
        self.embed.load()
        me = self.her_id()
        if me is not None and self.people.pop(str(me), None) is not None:
            log.info("removed the entry she had about herself")
        for d in self.people.values():
            self._migrate(d)
            junk = [f for f in d["facts"] if junk_fact(f["text"])]
            for f in junk:
                d["facts"].remove(f)
            if junk:
                log.info("%s: removed %d non-facts: %s", d.get("name"), len(junk), "; ".join(f["text"] for f in junk))
            for key in ("nickname", "her_nick"):
                v = str(d["slots"].get(key, {}).get("v", "")).lower()
                if d["slots"].get(key, {}).get("src") in ("asked", "named"):
                    continue
                if v in PET_NAMES or v == str(self.her_name() if self.her_id() else "").lower():
                    log.info("%s: removed %s %r, that's a pet name, not their name", d.get("name"), key, v)
                    d["slots"].pop(key)
        self._fix_voice_on_load()
        return self.people

    def _fix_voice_on_load(self):
        pending = sum(self.fix_voice_of(d) for d in self.people.values()) + self.fix_own_voice()
        if not pending:
            return
        if self.db.backup(self.db.path.with_name(VOICE_BACKUP)):
            log.info("saved a copy of her memory as %s before rewriting it", VOICE_BACKUP)
        log.info("rewrote %d memories that talked about her in third person", pending)
        self.dirty = True

    def fix_voice_of(self, d):
        names = self.app.messages.own_names()
        if not names:
            return 0
        she = "she" in str(d["slots"].get("pronouns", {}).get("v", "")).lower()
        changed = 0

        def fixed(text, pronouns=True):
            nonlocal changed
            new = voice.to_you(text, names, pronouns=pronouns, she_is_them=she)
            changed += new != text
            return new

        for key in NOTES_ABOUT_US:
            if d.get(key):
                d[key] = fixed(d[key])
        for key, field in LISTS_ABOUT_US:
            for item in d.get(key) or []:
                if item.get(field):
                    item[field] = fixed(item[field])
        for f in d["facts"]:
            f["text"] = fixed(f["text"], pronouns=False)
        return changed

    def fix_own_voice(self):
        names = self.app.messages.own_names()
        if not names:
            return 0
        kept, changed = [], 0
        for f in self.own["facts"]:
            if BEING_AI_OR_HUMAN.search(f["text"]):
                log.info(
                    "removed S%s %r: what she is comes from her identity note, not from memory", f["id"], f["text"]
                )
                changed += 1
                continue
            new = voice.own_fact_to_you(f["text"], names)
            changed += new != f["text"]
            f["text"] = new
            kept.append(f)
        self.own["facts"] = kept
        return changed

    def mark_dirty(self):
        self.dirty = True

    async def flush(self):
        if not (self.dirty or self.embed.dirty):
            return
        async with self.save_lock:
            self.dirty = False
            batch = self.db.changes(self.people, self.own)
            vectors = None
            if self.embed.dirty:
                vectors = self.embed.snapshot(
                    keep=[text for d in self.people.values() for _, _, text, _ in self._items(d)]
                )
            try:
                if batch:
                    await asyncio.to_thread(self.db.write, batch)
                    self.db.committed(batch)
                if vectors is not None:
                    await asyncio.to_thread(self.embed.write, vectors)
            except Exception:
                self.dirty = True
                raise

    def expire(self, days, now=None):
        if days <= 0:
            return []
        cutoff = (now or time.time()) - days * DAY
        gone = [uid for uid, d in self.people.items() if d.get("last_seen", now or time.time()) < cutoff]
        for uid in gone:
            self.people.pop(uid, None)
        if gone:
            self.dirty = True
            log.info("forgot %d people she hasn't talked to in %d days", len(gone), days)
        return gone

    def _migrate(self, d):
        d.setdefault("slots", {})
        d.setdefault("facts", [])
        d.setdefault("next_id", max([f["id"] for f in d["facts"]] or [0]) + 1)
        d.setdefault("since_notes", 0)
        d.setdefault("heard", 0)
        d.setdefault("added_since_tidy", 0)
        d.setdefault("gap_days", 0)
        d.setdefault("talks", 0)
        d.setdefault("episodes", [])
        d.setdefault("next_eid", max([e["id"] for e in d["episodes"]] or [0]) + 1)
        d.setdefault("threads", [])
        d.setdefault("next_tid", max([t["id"] for t in d["threads"]] or [0]) + 1)
        d.setdefault("since_reflect", 0)
        for note in d.pop("notes", []) or []:
            now = d.get("last_seen", time.time())
            d["facts"].append(
                {"id": d["next_id"], "text": note, "cat": "other", "src": "said", "t": now, "u": now, "n": 1}
            )
            d["next_id"] += 1
        for tp in d.pop("topics", []) or []:
            d["episodes"].append(
                {"id": d["next_eid"], "t": tp["t"], "u": tp["t"], "where": "", "summary": tp["text"], "mood": ""}
            )
            d["next_eid"] += 1
        for f in d["facts"]:
            if f.get("src") == "guess":
                f["src"] = "heard"
        for slot in d["slots"].values():
            if slot.get("src") == "guess":
                slot["src"] = "heard"
        activity.migrate(d)
        return d

    def get(self, user_id):
        if self.opted_out(user_id):
            return None
        return self.people.get(str(user_id))

    def opted_out(self, user_or_id):
        uid = getattr(user_or_id, "id", user_or_id)
        return uid is not None and int(uid) in self.app.cfg.memory_optout

    def note_age(self, user, age, why):
        if not self.enabled or self._is_her(user) or self.opted_out(user):
            return
        d = self.people.get(str(user.id))
        if d is None:
            now = time.time()
            d = self._migrate({"name": self.name_of(user), "first_seen": now, "last_seen": now, "session_start": now})
            self.people[str(user.id)] = d
        changes = []
        self._set_slot(d, "age", str(age), "said", changes, quote=why)
        if changes:
            log.info("%s: %s (%s)", self.name_of(user), " | ".join(changes), why)

    def forget(self, user_id):
        gone = self.people.pop(str(user_id), None) is not None
        if gone:
            self.dirty = True
        return gone

    def _is_her(self, user):
        return getattr(user, "id", None) is not None and user.id == self.her_id()

    def call_name(self, user_or_d):
        d = user_or_d if isinstance(user_or_d, dict) else self.get(getattr(user_or_d, "id", None))
        if not d:
            return None
        s = d.get("slots", {})
        for key in ("her_nick", "nickname"):
            if key in s and s[key].get("v"):
                return s[key]["v"]
        return None

    def all_names(self):
        out = set()
        for d in self.people.values():
            out |= {str(d.get("name", "")).lower(), str(d.get("username", "")).lower()}
            for key in ("her_nick", "nickname", "real_name"):
                if key in d.get("slots", {}):
                    out.add(str(d["slots"][key]["v"]).lower())
        out.discard("")
        return out

    def _names_of(self, d):
        return [n for n in (d.get("name"), self.call_name(d), d.get("slots", {}).get("real_name", {}).get("v")) if n]

    def touch(self, user, text):
        if not self.enabled or self._is_her(user) or self.opted_out(user):
            return
        now = time.time()
        d = self.people.get(str(user.id))
        if d is None:
            d = self._migrate({"name": self.name_of(user), "first_seen": now, "last_seen": now, "session_start": now})
            self.people[str(user.id)] = d
        d["name"] = self.name_of(user)
        d["username"] = getattr(user, "name", "")
        self.last_user[user.id] = user
        feelings = getattr(self.app, "feelings", None)
        if feelings is not None and feelings.people_on:
            feelings.settle(d, now)
        if now - d["last_seen"] > 2 * 3600:
            d["session_start"] = now
        d["gap_days"] = int((now - d["last_seen"]) // DAY) if now - d["last_seen"] > 3 * DAY else 0
        d["last_seen"] = now
        d["talks"] += 1
        d["since_notes"] += 1
        self._fast(d, text)
        self.dirty = True

    def overheard(self, user, text, channel):
        if not (self.enabled and self.overhear) or self._is_her(user) or getattr(user, "bot", False):
            return
        d = self.get(user.id)
        if not d:
            return
        d["heard"] = d.get("heard", 0) + 1
        self.last_user[user.id] = user
        self._fast(d, text)
        self.dirty = True
        self.maybe_update(user, channel)

    def _fast(self, d, text):
        changes = []
        if DISCLOSURE.search(text):
            d["disclosed"] = True
        m = AGE_NOW.search(text)
        if m:
            age = int(next(g for g in m.groups() if g))
            if 13 <= age <= 99:
                self._set_slot(d, "age", str(age), "said", changes)
        m = DONT_CALL.search(text)
        if m:
            bad = clean_name(m.group(1)) or ""
            bad = {bad.lower(), bad.split(" ")[0].lower()} - {""}
            for key in ("her_nick", "nickname"):
                if bad and key in d["slots"] and d["slots"][key]["v"].lower() in bad:
                    changes.append(f"- {key}: {d['slots'][key]['v']} (they don't like it)")
                    del d["slots"][key]
        else:
            m = CALL_ME.search(text)
            nick = clean_name(m.group(1)) if m else None
            if nick and nick.lower() != str(d.get("name", "")).lower():
                self._set_slot(d, "nickname", nick, "asked", changes)
                if "her_nick" in d["slots"]:
                    changes.append(f"- her_nick: {d['slots'].pop('her_nick')['v']} (they asked for {nick})")
        m = MY_NAME.search(text)
        name = clean_name(m.group(1)) if m else None
        if name and " " not in name:
            self._set_slot(d, "real_name", name, "said", changes)
        if changes:
            self._report(d["name"], changes, " (heard it directly)")

    def _asked_for(self, nick, theirs, her):
        nick = (clean_name(nick) or "").lower()
        if not nick or nick in PET_NAMES or nick == (her or "").lower():
            return False
        first = re.escape(nick.split(" ")[0])
        return bool(
            re.search(
                r"\b(?:call me|i go by|my name'?s|my name is|i'?m called|known as|name'?s)\W+(?:\w+\W+){0,2}"
                + first
                + r"\b",
                theirs,
                re.I,
            )
        )

    def her_said(self, user, lines):
        if not self.enabled or user is None or self._is_her(user):
            return
        d = self.get(user.id)
        if not d:
            return
        text = "\n".join(lines)
        for pattern in HER_NICK:
            m = pattern.search(text)
            nick = clean_name(m.group(1)) if m else None
            if nick and nick.lower() not in (str(d.get("name", "")).lower(), str(d.get("username", "")).lower()):
                changes = []
                self._set_slot(d, "her_nick", nick, "named", changes)
                if changes:
                    self._report(d["name"], changes, " (she named them)")
                return

    def _report(self, name, changes, why=""):
        log.info("%s: %s", name, " | ".join(changes))
        with contextlib.suppress(RuntimeError):
            self.app.tasks.spawn(self.log(f"**memory · {name}**{why}\n" + "\n".join(changes)))

    def current_age(self, d, now=None):
        now = now or time.time()
        s, b = d["slots"].get("age"), d["slots"].get("birthday")
        md = b.get("md") if b else None
        if s:
            if md:
                return s["v"] + birthdays_between(md, s["t"], now)
            return s["v"] + int((now - s["t"]) // (365.25 * DAY))
        if b and b.get("y") and md:
            today = dt.date.fromtimestamp(now)
            return today.year - b["y"] - (1 if today < birthday_in(today.year, md) else 0)
        return None

    def _slot_value(self, d, key):
        if key == "age":
            return self.current_age(d)
        s = d["slots"].get(key)
        return s["v"] if s else None

    def _set_slot(self, d, key, value, src, changes, quote=None):
        value = clean_fact(value)
        if not value or NON_ANSWER.match(value) or value.lower().replace(" ", "_") == key:
            return
        now = time.time()
        old = d["slots"].get(key)
        if old and rank(old.get("src")) >= rank("said") and rank(src) < rank("her"):
            return
        entry = {"v": cut(value, 80), "t": now, "src": src}
        if quote:
            entry["q"] = cut(clean_fact(quote), 160)
        if key == "age":
            m = re.search(r"\b(\d{1,3})\b", value)
            if not m or not 5 <= int(m.group(1)) <= 100:
                return
            entry["v"] = int(m.group(1))
        elif key == "birthday":
            p = parse_birthday(value)
            if p:
                entry["md"] = [p[0], p[1]]
                if p[2]:
                    entry["y"] = p[2]
                entry["v"] = f"{MONTHS[p[0] - 1]} {p[1]}" + (f" {p[2]}" if p[2] else "")
        elif key in ("nickname", "her_nick", "real_name"):
            name = clean_name(value)
            if not name:
                return
            entry["v"] = name
        old_value = self._slot_value(d, key)
        if old is not None:
            if str(old_value).lower() == str(entry["v"]).lower():
                was = old.get("src", "guess")
                old.update({k: v for k, v in entry.items() if k != "prev"})
                old["src"] = max((src, was), key=rank)
                return
            entry["prev"] = ([{"v": old_value, "t": old["t"]}] + old.get("prev", []))[:3]
            changes.append(f"~ {key}: {old_value} → {entry['v']}")
        else:
            changes.append(f"+ {key}: {entry['v']}" + (f" ({src})" if unsure(entry) else ""))
        d["slots"][key] = entry
        self.dirty = True

    def slot_summary(self, d, short=False, public=False):
        s = d["slots"]
        if public:
            return s["pronouns"]["v"] if "pronouns" in s else ""
        parts = []
        if "real_name" in s and not short:
            parts.append(f"real name {s['real_name']['v']}")
        age = self.current_age(d)
        if age is not None:
            parts.append(f"{age} years old" + (" (you heard, not sure)" if unsure(s.get("age", {})) else ""))
        if "pronouns" in s and not short:
            parts.append(s["pronouns"]["v"])
        if "location" in s:
            parts.append(f"lives in {s['location']['v']}")
        if "hometown" in s and not short:
            parts.append(f"originally from {s['hometown']['v']}")
        if "relationship" in s:
            parts.append(f"relationship: {s['relationship']['v']}")
        if not short:
            for key, label in (("job", "job"), ("school", "school"), ("birthday", "birthday")):
                if key in s:
                    parts.append(f"{label}: {s[key]['v']}")
        return ", ".join(parts)

    def _find(self, store, fid):
        return next((f for f in store["facts"] if f["id"] == fid), None)

    def _add_fact(self, store, text, cat, src, when, changes, prefix="F", name=None, quote=None, tags=None):
        text = clean_fact(text, name)
        if (
            not (3 <= len(text) <= 160)
            or NON_ANSWER.match(text)
            or text.lower().startswith(("nothing", "none", "no change"))
        ):
            return None
        if prefix == "F" and FIRST_PERSON.match(text):
            return None
        if junk_fact(text, person=(prefix == "F")):
            log.info("skipped a non-fact: %r", text)
            return None
        cat = norm_cat(cat)
        now = time.time()
        for f in store["facts"]:
            if similar(f["text"], text):
                f["n"] = f.get("n", 1) + 1
                f["u"] = now
                if rank(src) > rank(f.get("src")):
                    if unsure(f):
                        changes.append(f"✓ {prefix}{f['id']} confirmed: {f['text']}")
                    f["src"] = src
                    if quote:
                        f["q"] = cut(clean_fact(quote), 160)
                if when:
                    f["when"] = when
                if tags:
                    f["tags"] = list(dict.fromkeys((f.get("tags") or []) + tags))[:6]
                self.dirty = True
                return f
        f = {"id": store["next_id"], "text": text, "cat": cat, "src": src, "t": now, "u": now, "n": 1}
        if when:
            f["when"] = when
        if quote:
            f["q"] = cut(clean_fact(quote), 160)
        if tags:
            f["tags"] = tags[:6]
        store["next_id"] += 1
        store["facts"].append(f)
        store["added_since_tidy"] = store.get("added_since_tidy", 0) + 1
        changes.append(
            f"+ {prefix}{f['id']} [{cat}] {text}"
            + (f" @{when}" if when else "")
            + (f" ({src})" if unsure(f) else "")
            + (f'  ← "{cut(f["q"], 70)}"' if f.get("q") else "")
        )
        self.dirty = True
        return f

    def _update_fact(self, store, fid, text, when, changes, prefix="F", name=None, src="said", quote=None):
        f = self._find(store, fid)
        text = clean_fact(text, name)
        if f is None or not (3 <= len(text) <= 160) or text == f["text"] or NON_ANSWER.match(text):
            return
        if rank(f.get("src")) >= rank("said") and rank(src) < rank("her"):
            return
        changes.append(f"~ {prefix}{fid}: {f['text']} → {text}")
        f["text"], f["u"], f["src"] = text, time.time(), src
        if quote:
            f["q"] = cut(clean_fact(quote), 160)
        if when:
            f["when"] = when
        self.dirty = True

    def _forget_fact(self, store, fid, changes, prefix="F", why=""):
        f = self._find(store, fid)
        if f is None:
            return
        store["facts"].remove(f)
        changes.append(f"- {prefix}{fid} {f['text']}" + (f" ({why})" if why else ""))
        self.dirty = True

    def _merge_facts(self, store, ids, text, changes, prefix="F", name=None):
        facts = [f for f in (self._find(store, i) for i in dict.fromkeys(ids)) if f]
        text = clean_fact(text, name)
        if len(facts) < 2 or not (3 <= len(text) <= 200):
            return
        keep = min(facts, key=lambda f: f["id"])
        for f in facts:
            if f is not keep:
                store["facts"].remove(f)
        keep.update(
            text=text,
            u=time.time(),
            n=sum(f.get("n", 1) for f in facts),
            src=max((f.get("src", "said") for f in facts), key=rank),
        )
        tags = [t for f in facts for t in f.get("tags") or []]
        if tags:
            keep["tags"] = list(dict.fromkeys(tags))[:6]
        whens = [f["when"] for f in facts if f.get("when")]
        if whens:
            keep["when"] = max(whens)
        changes.append(f"= {'+'.join(prefix + str(f['id']) for f in facts)} → {prefix}{keep['id']}: {text}")
        self.dirty = True

    def fact_score(self, f, now):
        base = CATEGORIES.get(f.get("cat"), 0.6)
        recency = 0.5 ** ((now - f.get("u", f["t"])) / DAY / 60)
        score = base * (0.4 + 0.6 * recency) * (1 + 0.35 * math.log(f.get("n", 1)))
        return score * (0.6 if unsure(f) else 1.0)

    def _expire(self, store, changes, prefix="F"):
        today = dt.date.today()
        now = time.time()
        for f in list(store["facts"]):
            if f.get("cat") != "plans":
                continue
            when = parse_date(f.get("when", "")) if f.get("when") else None
            if when and (today - when).days > 7:
                self._forget_fact(store, f["id"], changes, prefix, "it's over")
            elif not when and now - f.get("u", f["t"]) > 21 * DAY:
                self._forget_fact(store, f["id"], changes, prefix, "old plan")
        for t in list(store.get("threads", [])):
            if t.get("done") or now - t["t"] > 21 * DAY:
                store["threads"].remove(t)
                changes.append(f"- T{t['id']} {t['text']} (too long ago)")

    def _evict(self, store, limit, changes, prefix="F"):
        now = time.time()
        while len(store["facts"]) > limit:
            worst = min(store["facts"], key=lambda f: self.fact_score(f, now))
            self._forget_fact(store, worst["id"], changes, prefix, "least important")

    def find_person(self, who):
        who = who.strip().lower()
        m = re.fullmatch(r"<@!?(\d+)>|(\d{15,20})", who)
        if m:
            uid = m.group(1) or m.group(2)
            return (uid, self.people[uid]) if uid in self.people else (None, None)

        def names(d):
            out = {str(d.get("name", "")).lower(), str(d.get("username", "")).lower()}
            for key in ("nickname", "her_nick", "real_name"):
                out.add(str(d["slots"].get(key, {}).get("v", "")).lower())
            return out - {""}

        for uid, d in self.people.items():
            if who in names(d):
                return uid, d
        for uid, d in self.people.items():
            if any(n.startswith(who) for n in names(d)):
                return uid, d
        return None, None

    def describe(self, d):
        now = time.time()
        lines = [
            f"**{d.get('name')}** (@{d.get('username', '?')}) · {d['talks']} messages · "
            f"last seen {said_ago(d['last_seen'])} · {d['since_notes'] + d.get('heard', 0)} not noted yet"
        ]
        feelings = getattr(self.app, "feelings", None)
        if feelings is not None and feelings.people_on:
            lines.append(feelings.describe_person(d).split("\n")[0].replace(f"**{d.get('name', '?')}** · ", "feels: "))
        for key in list(SLOTS) + ["her_nick"]:
            if key in d["slots"]:
                s = d["slots"][key]
                prev = f" (was {', '.join(str(p['v']) for p in s['prev'])})" if s.get("prev") else ""
                lines.append(f"`{key}` {self._slot_value(d, key)}{' (heard)' if unsure(s) else ''}{prev}")
        if d.get("rel"):
            lines.append(f"`rel` {d['rel']} (by hand)")
        if d.get("pinned"):
            lines.append(f"`pinned` {d['pinned']} (by hand)")
        if d.get("portrait"):
            lines.append(f"`portrait` {d['portrait']}")
        if d.get("talk_style"):
            lines.append(f"`with them` {d['talk_style']}")
        if d.get("bond"):
            lines.append(f"`bond` {d['bond']}")
        for kind in ("jokes", "shared", "avoid"):
            for j in d.get(kind) or []:
                lines.append(f"`{kind}` {j['text']} ({', '.join(j.get('from', []))})")
        if d.get("history"):
            lines.append(f"`history` {d['history']}")
        for e in d.get("episodes", [])[-4:]:
            lines.append(
                f"`E{e['id']}` {said_ago(e.get('u', e['t']), now)}"
                + (f" {e['where']}" if e.get("where") else "")
                + f": {e['summary']}"
                + (f" [{e['mood']}]" if e.get("mood") else "")
            )
        for t in d.get("threads", []):
            lines.append(f"`T{t['id']}` {t['text']} ({said_ago(t['t'], now)})")
        for f in sorted(d["facts"], key=lambda f: f["id"]):
            lines.append(
                f"`F{f['id']}` [{f['cat']}] {'(heard) ' if unsure(f) else ''}{f['text']}"
                + (f" @{f['when']}" if f.get("when") else "")
                + (f" ×{f['n']}" if f.get("n", 1) > 1 else "")
                + (f' ← "{cut(f["q"], 60)}"' if f.get("q") else "")
            )
        act = activity.summary(d, now)
        if act:
            lines.append(f"`discord` {act}")
        return "\n".join(lines)
