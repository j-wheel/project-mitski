import datetime as dt
import time

from mitski.core import logs
from mitski.core.text import cut
from mitski.core.texts import say, wording
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
                return text + (" " + say("memory.heard_from_someone", when=said_ago(obj["t"], now), name=call))
            return text + (" " + say("memory.they_told_you", when=said_ago(obj["t"], now)))
        if kind == "episode":
            where = (" " + say("memory.in_place", place=obj["where"])) if obj.get("where") else ""
            return say(
                "memory.you_talked",
                when=said_ago(obj.get("u", obj["t"]), now),
                where=where,
                summary=obj["summary"].rstrip("."),
            )
        if kind == "jokes":
            return say("memory.inside_joke", name=call, joke=obj["text"])
        if kind == "shared":
            return say("memory.in_common", name=call, thing=obj["text"])
        return str(obj)

    async def remember(self, user, query):
        d = self.get(getattr(user, "id", None))
        call = (self.call_name(d) if d else None) or self.name_of(user)
        hits = await self.search(d, query, 5) if d else []
        if not hits:
            return say("memory.remember_nothing", query=cut(query, 80), name=call)
        now = time.time()
        return (
            (say("memory.remember_found", name=call, query=cut(query, 80)) + " ")
            + "; ".join(self._line(d, kind, obj, call, now) for kind, obj in hits)
            + wording("memory.remember_only_this")
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
        feelings = getattr(self.app, "feelings", None)
        if not d or (d["talks"] < 3 and not d["facts"] and not d["slots"] and not d.get("episodes")):
            first = say("memory.stranger", name=name)
            feeling = feelings.regard_note(user, d, name) if d and feelings and feelings.stands_out(d, user.id) else ""
            profile = self.profile_line(d, name) if d and full else ""
            return f"{first} {profile} {feeling}".strip()
        now = time.time()
        today = dt.date.today()
        s = d["slots"]
        call = self.call_name(d) or name
        like = feelings.view(d, user.id, now)["like"] if feelings is not None and feelings.people_on else 0.0
        if d.get("rel"):
            rel = d["rel"]
        elif d["talks"] >= 60 and like >= 35:
            rel = wording("memory.rel_close_friend")
        elif d["talks"] >= 15 and like > -8:
            rel = wording("memory.rel_friend")
        elif d["talks"] >= 15:
            rel = wording("memory.rel_known")
        elif d["talks"] >= 3:
            rel = wording("memory.rel_few_times")
        else:
            rel = wording("memory.rel_new")
        out = [
            say("memory.talking_with", name=call)
            + ((" " + say("memory.discord_name", name=name)) if call.lower() != name.lower() else "")
            + f", {rel}."
        ]
        if "her_nick" in s:
            out.append(say("memory.her_nickname", nickname=s["her_nick"]["v"], nickname2=s["her_nick"]["v"]))
        elif "nickname" in s:
            out.append(say("memory.wants_to_be_called", nickname=s["nickname"]["v"], name=name))
        if d.get("calls_her"):
            out.append(say("memory.calls_you", name=call, pet_name=d["calls_her"]["v"]))
        if d.get("pinned"):
            out.append(d["pinned"].rstrip())
        feeling = feelings.regard_note(user, d, call) if feelings is not None else ""
        if feeling:
            out.append(feeling)
        if d.get("gap_days"):
            out.append(say("memory.not_talked_in", days=d["gap_days"]))
        if full and d.get("portrait"):
            out.append(say("memory.who_they_are", name=call, portrait=d["portrait"].rstrip()))
        if full and d.get("talk_style"):
            out.append(say("memory.how_you_are", name=call, talk_style=d["talk_style"].rstrip()))
        about = self.slot_summary(d)
        if about:
            out.append(say("memory.what_you_know", name=call, about=about))
        profile = self.profile_line(d, call) if full else ""
        if profile:
            out.append(profile)
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
                    say(
                        "memory.changed_field",
                        when=said_ago(slot["t"], now),
                        field=SLOT_LABELS[key],
                        verb=verb,
                        value=self._slot_value(d, key),
                        old=slot["prev"][0]["v"],
                    )
                )
        age = self.current_age(d)
        if age is not None and age < 18:
            out.append(say("memory.is_minor", name=call, age=age))
        b = s.get("birthday")
        if b and b.get("md"):
            nxt = birthday_in(today.year, b["md"])
            if nxt < today:
                nxt = birthday_in(today.year + 1, b["md"])
            days = (nxt - today).days
            if days == 0:
                out.append(say("memory.birthday_today", name=call))
            elif days <= 7:
                out.append(say("memory.birthday_soon", name=call, days=days, s="s" if days > 1 else ""))
            elif (today - birthday_in(today.year, b["md"])).days in range(1, 4):
                out.append(say("memory.birthday_was", name=call))
        if d.get("bond") and not (full and d.get("portrait")):
            out.append(say("memory.get_along", bond=d["bond"].rstrip(".!")))
        act = activity.summary(d, now)
        if act:
            out.append(say("memory.on_discord", name=call, activity=act))
        if full:
            if d.get("jokes"):
                out.append(
                    (say("memory.inside_jokes", name=call) + " ") + "; ".join(j["text"] for j in d["jokes"]) + "."
                )
            if d.get("shared"):
                out.append((say("memory.you_both", name=call) + " ") + "; ".join(j["text"] for j in d["shared"]) + ".")
            if d.get("avoid"):
                out.append(
                    (say("memory.stay_away_from", name=call) + " ") + "; ".join(j["text"] for j in d["avoid"]) + "."
                )
            if d.get("history"):
                out.append(say("memory.history", name=call, history=d["history"].rstrip()))
        earlier = self._last_episodes(d, 2 if full else 1, now)
        if earlier:
            last = earlier[-1]
            where = say("memory.last_place", place=last["where"]) if last.get("where") else ""
            line = say(
                "memory.last_time",
                when=said_ago(last.get("u", last["t"]), now),
                where=where,
                summary=last["summary"].rstrip("."),
            )
            if len(earlier) > 1:
                line += " " + say(
                    "memory.before_that",
                    when=said_ago(earlier[-2].get("u", earlier[-2]["t"]), now),
                    summary=earlier[-2]["summary"].rstrip("."),
                )
            out.append(line)
        threads = [t for t in d.get("threads", []) if not t.get("done")]
        if threads and full:
            out.append(
                (say("memory.still_open", name=call) + " ")
                + "; ".join(t["text"].rstrip(".") for t in threads[-3:])
                + "."
            )
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
            out.append((say("memory.coming_up", name=call) + " ") + "; ".join(upcoming[:4]) + ".")
        if passed:
            out.append(
                (say("memory.recently", name=call) + " ") + "; ".join(passed[:3]) + wording("memory.ask_how_it_went")
            )
        picked = self.pick_facts(d, context, self.facts_in_prompt if full else 4, now)
        said = [f["text"] for f in picked if not unsure(f)]
        heard = [f["text"] for f in picked if unsure(f)]
        if said:
            out.append((say("memory.told_you", name=call) + " ") + "; ".join(said) + ".")
        if heard:
            out.append((say("memory.heard_about", name=call) + " ") + "; ".join(heard) + ".")
        if said or about or earlier or upcoming or passed or d.get("portrait"):
            out.append(wording("memory.use_it_naturally"))
        return " ".join(out)

    def others_blurb(self, users, context=""):
        if not self.enabled:
            return ""
        lines, minors = [], []
        for u in users[:6]:
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
                (" " + say("memory.discord_name_call", discord_name=self.name_of(u), name=call))
                if call.lower() != self.name_of(u).lower()
                else ""
            )
            bits = [b for b in [self.slot_summary(d, public=True)] if b]
            bits += [
                f["text"] + ((" " + wording("memory.heard_short")) if unsure(f) else "")
                for f in self.pick_facts(d, context, 3, public=True)
            ]
            games = activity.games_summary(d.get("activity") or {}, n=1)
            if games:
                bits.append(games)
            if (bits or label != call) and len(lines) < 4:
                lines.append(label + (": " + "; ".join(bits) if bits else ""))
        out = ((wording("memory.others_here") + " ") + " | ".join(lines) + ".") if lines else ""
        if minors:
            out += (" " if out else "") + (
                say(
                    "memory.minors_here",
                    names=", ".join(minors),
                    are=wording("memory.is_a_minor") if len(minors) == 1 else wording("memory.are_minors"),
                )
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
                out.append(say("memory.hook_birthday_today", name=call))
            elif days == 1:
                out.append(say("memory.hook_birthday_tomorrow", name=call))
        for f in d["facts"]:
            when = parse_date(f["when"]) if f.get("cat") == "plans" and f.get("when") else None
            if when is None:
                continue
            n = (when - today).days
            if 0 <= n <= 2:
                out.append(say("memory.hook_plan", name=call, plan=f["text"], when=until(when, today)))
            elif -3 <= n < 0:
                out.append(say("memory.hook_plan_passed", name=call, plan=f["text"], when=until(when, today)))
        for key, slot in d["slots"].items():
            if (
                key in SLOT_LABELS
                and key not in ("her_nick", "nickname")
                and slot.get("prev")
                and now - slot["t"] < DAY
                and not unsure(slot)
            ):
                out.append(
                    say(
                        "memory.hook_changed",
                        name=call,
                        field=SLOT_LABELS[key],
                        value=self._slot_value(d, key),
                        old=slot["prev"][0]["v"],
                    )
                )
        fresh = now - d.get("session_start", 0) < 15 * 60
        threads = [t for t in d.get("threads", []) if not t.get("done")]
        if fresh and threads:
            out.append((wording("memory.hook_open") + " ") + "; ".join(t["text"].rstrip(".") for t in threads[-2:]))
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
        return ((wording("memory.about_herself") + " ") + "; ".join(f["text"] for f in picked) + ".") if picked else ""
