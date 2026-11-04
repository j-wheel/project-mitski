import datetime as dt
import time

from mitski.core import logs
from mitski.core.text import cut
from mitski.memory import activity
from mitski.memory.dates import DAY, birthday_in, parse_date, said_ago, until
from mitski.memory.embeddings import cosine
from mitski.memory.heuristics import unsure, words
from mitski.memory.schema import PUBLIC_CATEGORIES, SLOT_LABELS

log = logs.get("memory")


class RecallMixin:
    def pick_facts(self, store, context, limit, now=None, public=False):
        now = now or time.time()
        ctx = words(context or "")
        facts = [
            f for f in store["facts"] if f.get("cat") != "plans" and (not public or f.get("cat") in PUBLIC_CATEGORIES)
        ]

        def score(f):
            overlap = len(ctx & words(f["text"] + " " + " ".join(f.get("tags") or []))) if ctx else 0
            return self.fact_score(f, now) + 0.6 * overlap + (0.3 if now - f["t"] < 2 * DAY else 0)

        return sorted(facts, key=score, reverse=True)[:limit]

    def _items(self, d):
        out = []
        for f in d.get("facts", []):
            out.append(("fact", f["id"], f["text"] + (" (" + ", ".join(f["tags"]) + ")" if f.get("tags") else ""), f))
        for e in d.get("episodes", []):
            if e.get("summary"):
                out.append(("episode", e["id"], e["summary"], e))
        for kind in ("jokes", "shared"):
            for i, j in enumerate(d.get(kind) or []):
                out.append((kind, i, j["text"], j))
        return out

    def _keyword_hits(self, d, query, k):
        q = words(query or "")
        if not q:
            return []
        now = time.time()
        scored = []
        for kind, _key, text, obj in self._items(d):
            overlap = len(q & words(text))
            if overlap:
                boost = self.fact_score(obj, now) if kind == "fact" else 0.5
                scored.append((overlap + 0.3 * boost, kind, obj))
        scored.sort(key=lambda x: -x[0])
        return [(kind, obj) for _, kind, obj in scored[:k]]

    async def search(self, user_or_d, query, k=5):
        d = user_or_d if isinstance(user_or_d, dict) else self.get(getattr(user_or_d, "id", None))
        if not d or not (query or "").strip():
            return []
        items = self._items(d)
        if self.embed.active and items:
            vecs = await self.embed.docs([text for _, _, text, _ in items])
            qv = await self.embed.query(cut(query, 1200)) if vecs else None
            if vecs and qv:
                scored = sorted(
                    ((cosine(qv, v), kind, obj) for (kind, _, _, obj), v in zip(items, vecs, strict=False)),
                    key=lambda x: -x[0],
                )
                best = scored[0][0]
                keep = [(kind, obj) for sc, kind, obj in scored[:k] if sc >= max(0.35, best - 0.12)]
                for hit in self._keyword_hits(d, query, 2):
                    if hit not in keep:
                        keep.append(hit)
                return keep[:k]
        return self._keyword_hits(d, query, k)

    async def prefetch(self, user, context):
        if not self.enabled or user is None or not self.get(user.id):
            return
        try:
            hits = await self.search(user, context, 4)
        except Exception:
            log.warning("recall failed", exc_info=True)
            hits = []
        self.recalled[user.id] = (time.time(), hits)

    def _line(self, d, kind, obj, call, now=None):
        now = now or time.time()
        if kind == "fact":
            text = obj["text"]
            text = f"{call}'s {text[6:]}" if text.lower().startswith("their ") else f"{call} {text}"
            if unsure(obj):
                return (
                    text
                    + f" (someone else said that, {said_ago(obj['t'], now)}, it's not from {call} so you're not sure)"
                )
            return text + f" (they told you {said_ago(obj['t'], now)})"
        if kind == "episode":
            where = f" in {obj['where']}" if obj.get("where") else ""
            return f"{said_ago(obj.get('u', obj['t']), now)}{where} you two talked: {obj['summary'].rstrip('.')}"
        if kind == "jokes":
            return f"an inside joke you have with {call}: {obj['text']}"
        if kind == "shared":
            return f"something you and {call} have in common: {obj['text']}"
        return str(obj)

    async def remember(self, user, query):
        d = self.get(getattr(user, "id", None))
        call = (self.call_name(d) if d else None) or self.name_of(user)
        hits = await self.search(d, query, 5) if d else []
        if not hits:
            return (
                f'You searched your memory for "{cut(query, 80)}" with {call} and found nothing, so you don\'t '
                f"remember that. Say so honestly (or ask them to remind you), don't make anything up."
            )
        now = time.time()
        return (
            f'What you remember with {call} about "{cut(query, 80)}": '
            + "; ".join(self._line(d, kind, obj, call, now) for kind, obj in hits)
            + ". Only this, nothing more: don't add details you don't actually remember."
        )

    def _last_episodes(self, d, n=2, now=None):
        now = now or time.time()
        session = d.get("session_start", 0)
        return [e for e in d.get("episodes", []) if e.get("u", e["t"]) < max(session, now - 3600)][-n:]

    def blurb(self, user, context="", full=True):
        if not self.enabled or user is None:
            return ""
        name = self.name_of(user)
        d = self.get(user.id)
        if not d or (d["talks"] < 3 and not d["facts"] and not d["slots"] and not d.get("episodes")):
            return (
                f"You're talking with {name}, you don't really know them yet. You haven't talked before, so "
                f"there's nothing you remember with them."
            )
        now = time.time()
        today = dt.date.today()
        s = d["slots"]
        call = self.call_name(d) or name
        if d.get("rel"):
            rel = d["rel"]
        elif d["talks"] >= 60 and d["vibe"] >= 0.5:
            rel = "one of your close friends"
        elif d["talks"] >= 15:
            rel = "a friend of yours"
        elif d["talks"] >= 3:
            rel = "someone you've talked to a few times"
        else:
            rel = "someone you're just getting to know"
        out = [
            f"You're talking with {call}"
            + (f" (discord name {name})" if call.lower() != name.lower() else "")
            + f", {rel}."
        ]
        if "her_nick" in s:
            out.append(
                f'"{s["her_nick"]["v"]}" is the nickname you gave them, so when you use their name, '
                f"call them {s['her_nick']['v']}."
            )
        elif "nickname" in s:
            out.append(
                f"They want to be called {s['nickname']['v']}, so when you use their name, "
                f"always say {s['nickname']['v']}, never {name}."
            )
        if d.get("calls_her"):
            out.append(f"{call} likes calling you {d['calls_her']['v']}.")
        if d.get("pinned"):
            out.append(d["pinned"].rstrip())
        if d["vibe"] <= -2 and not d.get("rel"):
            out.append(f"{call} has been mean to you lately, so you're a bit sassy and guarded with them.")
        elif d["vibe"] >= 2.5:
            out.append(f"{call} is always sweet to you, so you're extra warm with them.")
        if d.get("gap_days"):
            out.append(f"You haven't talked in {d['gap_days']} days.")
        if full and d.get("portrait"):
            out.append(f"Who {call} is to you: {d['portrait'].rstrip()}")
        if full and d.get("talk_style"):
            out.append(f"How you are with {call}: {d['talk_style'].rstrip()}")
        about = self.slot_summary(d)
        if about:
            out.append(f"What you know about {call}: {about}.")
        for key, slot in s.items():
            if (
                key in SLOT_LABELS
                and key != "her_nick"
                and slot.get("prev")
                and now - slot["t"] < 2 * DAY
                and not unsure(slot)
            ):
                verb = "are" if key == "pronouns" else "is"
                out.append(
                    f"They told you {said_ago(slot['t'], now)} that their {SLOT_LABELS[key]} {verb} "
                    f"{self._slot_value(d, key)} (you thought {slot['prev'][0]['v']} before)."
                )
        age = self.current_age(d)
        if age is not None and age < 18:
            out.append(
                f"{call} is {age}, a minor. Keep everything with them friendly and age-appropriate: "
                f"no flirting, nothing romantic or sexual."
            )
        b = s.get("birthday")
        if b and b.get("md"):
            nxt = birthday_in(today.year, b["md"])
            if nxt < today:
                nxt = birthday_in(today.year + 1, b["md"])
            days = (nxt - today).days
            if days == 0:
                out.append(f"Today is {call}'s birthday!")
            elif days <= 7:
                out.append(f"{call}'s birthday is in {days} day{'s' if days > 1 else ''}.")
            elif (today - birthday_in(today.year, b["md"])).days in range(1, 4):
                out.append(f"{call}'s birthday was a few days ago.")
        if d.get("bond") and not (full and d.get("portrait")):
            out.append(f"How you two get along: {d['bond'].rstrip('.!')}.")
        act = activity.summary(d, now)
        if act:
            out.append(f"What {call} does on discord: {act}.")
        if full:
            if d.get("jokes"):
                out.append(f"Inside jokes you have with {call}: " + "; ".join(j["text"] for j in d["jokes"]) + ".")
            if d.get("shared"):
                out.append(f"You and {call} both: " + "; ".join(j["text"] for j in d["shared"]) + ".")
            if d.get("avoid"):
                out.append(f"Stay away from with {call}: " + "; ".join(j["text"] for j in d["avoid"]) + ".")
            if d.get("history"):
                out.append(f"Your history with {call}: {d['history'].rstrip()}")
        earlier = self._last_episodes(d, 2 if full else 1, now)
        if earlier:
            last = earlier[-1]
            where = f", in {last['where']}" if last.get("where") else ""
            line = f"Last time you talked ({said_ago(last.get('u', last['t']), now)}{where}): {last['summary'].rstrip('.')}."
            if len(earlier) > 1:
                line += f" Before that ({said_ago(earlier[-2].get('u', earlier[-2]['t']), now)}): {earlier[-2]['summary'].rstrip('.')}."
            out.append(line)
        threads = [t for t in d.get("threads", []) if not t.get("done")]
        if threads and full:
            out.append(f"Still open with {call}: " + "; ".join(t["text"].rstrip(".") for t in threads[-3:]) + ".")
        upcoming, passed = [], []
        for f in d["facts"]:
            if f.get("cat") != "plans":
                continue
            when = parse_date(f["when"]) if f.get("when") else None
            if when and when < today:
                passed.append(f"{f['text']} ({until(when, today)})")
            else:
                upcoming.append(f"{f['text']}" + (f" ({until(when, today)})" if when else ""))
        if upcoming:
            out.append(f"Coming up for {call}: " + "; ".join(upcoming[:4]) + ".")
        if passed:
            out.append(f"Recently for {call}: " + "; ".join(passed[:3]) + ". You could ask how it went.")
        picked = self.pick_facts(d, context, self.facts_in_prompt if full else 4, now)
        said = [f["text"] for f in picked if not unsure(f)]
        heard = [f["text"] for f in picked if unsure(f)]
        if said:
            out.append(f"Things {call} told you: " + "; ".join(said) + ".")
        if heard:
            out.append(
                f"Things other people said about {call}, not {call} themselves (you're not sure they're true, "
                f"don't state them as fact): " + "; ".join(heard) + "."
            )
        if said or about or earlier or upcoming or passed or d.get("portrait"):
            out.append(
                "Use what you remember the way someone who really knows them would: bring one thing up only when it fits, "
                "never list facts, and don't ask about things you already know. What's written here is all "
                "you remember: if they bring up something from before that isn't here, you don't remember "
                "it, so say so or ask. Never make up things you did or talked about together."
            )
        return " ".join(out)

    def others_blurb(self, users, context=""):
        if not self.enabled:
            return ""
        lines, minors = [], []
        for u in users[:4]:
            d = self.get(u.id)
            if not d:
                continue
            call = self.call_name(d) or self.name_of(u)
            age = self.current_age(d)
            if age is not None and age < 18:
                minors.append(call)
            if d["talks"] < 3 and not d["facts"] and not self.call_name(d):
                continue
            label = call + (
                f" (discord name {self.name_of(u)}, call them {call})"
                if call.lower() != self.name_of(u).lower()
                else ""
            )
            bits = [b for b in [self.slot_summary(d, public=True)] if b]
            bits += [
                f["text"] + (" (heard, not sure)" if unsure(f) else "")
                for f in self.pick_facts(d, context, 2, public=True)
            ]
            games = activity.games_summary(d.get("activity") or {}, n=1)
            if games:
                bits.append(games)
            if (bits or label != call) and len(lines) < 3:
                lines.append(label + (": " + "; ".join(bits) if bits else ""))
        out = ("Other people in this chat you know: " + " | ".join(lines) + ".") if lines else ""
        if minors:
            out += (" " if out else "") + (
                f"{', '.join(minors)} {'is a minor' if len(minors) == 1 else 'are minors'}, "
                f"so keep the whole chat age-appropriate: no flirting, nothing sexual."
            )
        return out

    def hooks(self, user, context="", limit=3):
        if not self.enabled or user is None:
            return []
        d = self.get(user.id)
        if not d:
            return []
        now, today = time.time(), dt.date.today()
        call = self.call_name(d) or self.name_of(user)
        out = []
        b = d["slots"].get("birthday")
        if b and b.get("md"):
            days = (birthday_in(today.year, b["md"]) - today).days
            if days == 0:
                out.append(f"it's {call}'s birthday today")
            elif days == 1:
                out.append(f"{call}'s birthday is tomorrow")
        for f in d["facts"]:
            when = parse_date(f["when"]) if f.get("cat") == "plans" and f.get("when") else None
            if when is None:
                continue
            n = (when - today).days
            if 0 <= n <= 2:
                out.append(f"{call} {f['text']} ({until(when, today)})")
            elif -3 <= n < 0:
                out.append(f"{call} {f['text']} ({until(when, today)}), you could ask how it went")
        for key, slot in d["slots"].items():
            if (
                key in SLOT_LABELS
                and key not in ("her_nick", "nickname")
                and slot.get("prev")
                and now - slot["t"] < DAY
                and not unsure(slot)
            ):
                out.append(
                    f"{call} recently told you their {SLOT_LABELS[key]} is {self._slot_value(d, key)} "
                    f"(you used to think {slot['prev'][0]['v']})"
                )
        fresh = now - d.get("session_start", 0) < 15 * 60
        threads = [t for t in d.get("threads", []) if not t.get("done")]
        if fresh and threads:
            out.append("still open from before: " + "; ".join(t["text"].rstrip(".") for t in threads[-2:]))
        got = self.recalled.get(user.id)
        hits = got[1] if got and now - got[0] < 120 else self._keyword_hits(d, context, limit)
        for kind, obj in hits[:limit]:
            if kind == "fact" and obj.get("cat") == "plans" and obj.get("when"):
                continue
            out.append(self._line(d, kind, obj, call, now))
        return out[: limit + 3]

    def self_blurb(self, context=""):
        if not (self.enabled and self.self_notes) or not self.own["facts"]:
            return ""
        picked = self.pick_facts(self.own, context, 8)
        return (
            (
                "Things you've told people about yourself before (stay consistent with them): "
                + "; ".join(f["text"] for f in picked)
                + "."
            )
            if picked
            else ""
        )
