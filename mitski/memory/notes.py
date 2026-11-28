import asyncio
import datetime as dt
import json
import re
import time

from mitski.core import logs
from mitski.core.text import cut
from mitski.core.texts import fill, fill_all, say, wording
from mitski.llm import gpu
from mitski.llm.client import tokens_guess
from mitski.llm.helper import parse_json
from mitski.memory import activity
from mitski.memory.dates import DAY, plan_date, said_ago
from mitski.memory.heuristics import (
    HER_NICK,
    NON_ANSWER,
    PET_NAMES,
    clean_fact,
    clean_name,
    find_evidence,
    norm_cat,
    norm_slot,
    norm_text,
    similar,
    unsure,
    whole,
)
from mitski.memory.schema import (
    BOND_MAX,
    EVIDENCE,
    HISTORY_MAX,
    MONTHS,
    PORTRAIT_MAX,
    REFLECT,
    SCHEMA,
    SLOTS,
    STYLE_MAX,
    SUMMARY_MAX,
)
from mitski.social.feelings import CLOSE, KINDS

log = logs.get("memory")

NOTES_TOKENS = 1300
REFLECT_TOKENS = 1100
NOTES_CHAT_CHARS = 18000
FEELING_ITEM = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": list(KINDS)},
        "intensity": {"type": "integer", "minimum": 1, "maximum": 3},
        "evidence": EVIDENCE,
        "why": {"type": "string", "maxLength": 100},
    },
    "required": ["kind", "intensity", "evidence", "why"],
    "additionalProperties": False,
}
LOOK_UP = {"type": "array", "maxItems": 2, "items": {"type": "string", "maxLength": 60}}
NOTES_SCHEMA = {
    **SCHEMA,
    "properties": {
        **SCHEMA["properties"],
        "feelings": {"type": "array", "maxItems": 5, "items": FEELING_ITEM},
        "look_up": LOOK_UP,
    },
    "required": [*SCHEMA["required"], "feelings", "look_up"],
}
FEELING_KINDS = "\n".join(f"- {kind}: {meaning}" for kind, (meaning, _, _) in KINDS.items())


class NotesMixin:
    def maybe_update(self, user, channel, force=False):
        if not (self.enabled and self.notes) or getattr(user, "bot", False) or self._is_her(user):
            return
        d = self.get(user.id)
        if not d:
            return
        self.last_channel[user.id] = channel
        self.last_user[user.id] = user
        if user.id in self.running:
            return
        pending = d["since_notes"] + d.get("heard", 0)
        due = (
            force
            or d["since_notes"] >= self.notes_every
            or d.get("heard", 0) >= self.overhear_every
            or (d.get("disclosed") and pending >= 1)
        )
        if due and (force or time.time() - d.get("notes_at", 0) >= self.min_gap) and self._budget():
            self.running.add(user.id)
            self.app.tasks.spawn(self.update(user, channel))
        elif pending >= 1 and user.id not in self.flushes:
            self.flushes[user.id] = self.app.tasks.spawn(self._flush_later(user))

    async def _flush_later(self, user):
        try:
            await asyncio.sleep(self.idle)
            d = self.get(user.id)
            if not d or user.id in self.running:
                return
            worth_it = d["since_notes"] + d.get("heard", 0) >= 2 or (d.get("disclosed") and d["since_notes"] >= 1)
            if worth_it and self._budget():
                self.running.add(user.id)
                await self.update(user, self.last_channel.get(user.id))
        finally:
            self.flushes.pop(user.id, None)

    def _budget(self):
        now = time.time()
        while self.update_times and now - self.update_times[0] > 3600:
            self.update_times.popleft()
        if len(self.update_times) >= self.max_per_hour:
            return False
        self.update_times.append(now)
        return True

    def _known_text(self, d):
        label = wording("memory.known_labels")
        lines = []
        for key in list(SLOTS) + ["her_nick"]:
            v = self._slot_value(d, key)
            if v is not None:
                name = label["her_nick"] if key == "her_nick" else key
                lines.append(f"{name}: {v}" + (" " + label["heard_field"] if unsure(d["slots"][key]) else ""))
        for f in sorted(d["facts"], key=lambda f: f["id"]):
            lines.append(
                f"F{f['id']} [{f['cat']}] "
                + f["text"]
                + (" " + label["heard_fact"] if unsure(f) else "")
                + (" " + fill(label["date"], date=f["when"]) if f.get("when") else "")
            )
        if d.get("rel"):
            lines.append(fill(label["rel"], rel=d["rel"]))
        if d.get("pinned"):
            lines.append(fill(label["pinned"], pinned=d["pinned"]))
        if d.get("bond"):
            lines.append(fill(label["bond"], bond=d["bond"]))
        profile = self.profile_line(d, "their")
        if profile:
            lines.append(profile.replace("their's", "their", 1) + " " + label["their_profile"])
        return "\n".join(lines) or label["nothing"]

    def _instructions(self, her):
        today = dt.date.today()
        yesterday = today - dt.timedelta(days=1)
        monday = today + dt.timedelta(days=(7 - today.weekday()) or 7)
        example = fill_all(
            wording("memory.notes_example"),
            birthday=f"{MONTHS[yesterday.month - 1]} {yesterday.day}",
            monday=monday.isoformat(),
        )
        return say(
            "memory.notes_system",
            her=her,
            fields=", ".join(f"{k} = {v}" for k, v in SLOTS.items()),
            today=f"{today.strftime('%A')} {today.isoformat()}",
            feeling_kinds=FEELING_KINDS,
            example=json.dumps(example, ensure_ascii=False),
        )

    def _data_text(self, d, name, her, earlier, new, line, think=False):
        now = time.time()
        text = say("memory.notes_known", name=name, known=self._known_text(d)) + "\n"
        threads = [t for t in d.get("threads", []) if not t.get("done")]
        if threads:
            text += (
                "\n"
                + say("memory.notes_threads", name=name)
                + "\n"
                + "\n".join(f"T{t['id']} {t['text']} ({said_ago(t['t'], now)})" for t in threads)
                + "\n"
            )
        past = self._last_episodes(d, 3, now)
        if past:
            text += (
                "\n"
                + say("memory.notes_episodes", her=her)
                + "\n"
                + "\n".join(
                    f"E{e['id']} ({said_ago(e.get('u', e['t']), now)}"
                    + (f", {e['where']}" if e.get("where") else "")
                    + "): "
                    + e["summary"]
                    for e in past
                )
                + "\n"
            )
        current = self._current_episode(d)
        if current:
            text += "\n" + say("memory.notes_current", summary=current["summary"]) + "\n"
        if self.self_notes and self.own["facts"]:
            own = sorted(self.own["facts"], key=lambda f: -f["id"])[:25]
            text += (
                "\n"
                + say("memory.notes_her_facts", her=her)
                + "\n"
                + "\n".join(f"S{f['id']} [{f['cat']}] {f['text']}" for f in sorted(own, key=lambda f: f["id"]))
                + "\n"
            )
        if earlier:
            text += "\n" + wording("memory.notes_earlier") + "\n" + "\n".join(map(line, earlier)) + "\n"
        text += "\n" + wording("memory.notes_new") + "\n" + "\n".join(map(line, new)) + "\n\n"
        if think:
            text += say("memory.notes_think", name=name, her=her)
        else:
            text += say("memory.notes_json_only", name=name)
        return text

    def _aimed(self, user, msgs, me):
        addressing = getattr(self.app, "addressing", None)
        feelings = getattr(self.app, "feelings", None)
        hers = [m for m in msgs if m.author.id == me]
        out = {}
        for m in msgs:
            if m.author.id == me:
                out[m.id] = ("her", None)
            elif m.author.id != user.id:
                out[m.id] = ("other", None)
            elif addressing is not None and addressing.aimed_at_her(m, hers):
                out[m.id] = ("them", None)
            else:
                target = addressing.target_of(m) if addressing is not None else None
                close = target is not None and feelings is not None and feelings.like_of(target) >= CLOSE
                out[m.id] = ("them_friend" if close else "them_else", target)
        return out

    def _current_episode(self, d):
        sid = d.get("session_start") or d.get("first_seen")
        e = d["episodes"][-1] if d.get("episodes") else None
        return e if e is not None and e.get("sid") == sid else None

    async def update(self, user, channel):
        gpu.background()
        name = self.name_of(user)
        her = self.her_name()
        try:
            d = self.get(user.id)
            if d is None or channel is None:
                return
            msgs = await self.chat_of(user, channel)
            upto = d.get("notes_upto", 0)
            new = [m for m in msgs if m.id > upto][-60:]
            if not any(m.author.id == user.id for m in new):
                d["since_notes"], d["heard"], d["disclosed"] = 0, 0, False
                return
            earlier = [m for m in msgs if m.id <= upto][-6:]
            me = self.her_id()

            aimed = self._aimed(user, earlier + new, me)

            def line(m):
                who = her if m.author.id == me else self.name_of(m.author)
                kind, target = aimed.get(m.id, (None, None))
                to = f" (to {her})" if kind == "them" else f" (to {self.name_of(target)})" if target else ""
                return f"{who}{to}: {cut(self.text_of(m), 400)}"

            instructions = self._instructions(her)
            limit = NOTES_CHAT_CHARS
            if not self.app.helper.external:
                fixed = tokens_guess(instructions + self._data_text(d, name, her, earlier, [], line))
                limit = self.app.llm.room_chars(NOTES_TOKENS * 2 + self.app.helper.think_tokens + fixed, limit)
            while len(new) > 1 and sum(len(line(m)) + 1 for m in new) > limit:
                new = new[1:]

            def who(m):
                return "her" if m.author.id == me else "them" if m.author.id == user.id else "other"

            evidence = [(who(m), self.text_of(m)) for m in earlier + new]
            to_her = [(aimed.get(m.id, ("other", None))[0], self.text_of(m)) for m in earlier + new]
            where = f"#{channel.name}" if getattr(channel, "name", None) else "dms"
            took_part = any(m.author.id == me for m in new)
            answer = await self.app.helper.ask(
                instructions,
                self._data_text(d, name, her, earlier, new, line, think=self.think_on),
                NOTES_SCHEMA,
                NOTES_TOKENS,
                think=True,
            )
            out = answer.text
            self.last_raw[user.id] = (f"(thought)\n{answer.thought}\n\n(answer)\n" if answer.thought else "") + out
            data = parse_json(out)
            if data is None:
                changes = []
                log.info("%s: the notes model wrote nothing usable: %r", name, cut(re.sub(chr(10), " ", out), 200))
            else:
                changes = self.apply_json(d, data, self._names_of(d), her, evidence, where, took_part)
                feelings = getattr(self.app, "feelings", None)
                if feelings is not None:
                    changes += feelings.appraise(user, d, data.get("feelings"), to_her)
                knowledge = getattr(self.app, "knowledge", None)
                if knowledge is not None:
                    knowledge.want(data.get("look_up"), name)
                self.fix_voice_of(d)
                self.fix_own_voice()
            self._expire(d, changes)
            d["since_reflect"] = d.get("since_reflect", 0) + sum(1 for c in changes if not c.startswith("✗"))
            d["notes_upto"] = max(m.id for m in new)
            d["since_notes"], d["heard"], d["disclosed"], d["notes_at"] = 0, 0, False, time.time()
            if self._should_reflect(d):
                downtime = getattr(self.app, "downtime", None)
                if self._must_reflect(d) or downtime is None or not downtime.on:
                    changes += await self.reflect(d, name)
                else:
                    downtime.later(
                        f"reflect-{user.id}", lambda uid=user.id: self.reflect_now(uid), f"rethinking {name}"
                    )
            self._evict(d, self.facts_max, changes)
            self._evict(self.own, self.self_max, changes, "S")
            self.dirty = True
            if changes:
                log.info("%s: %s", name, " | ".join(changes))
                await self.log(f"**memory · {name}**\n" + "\n".join(changes))
            else:
                log.info("%s: nothing new", name)
            if self.embed.active:
                await self.embed.docs([text for _, _, text, _ in self._items(d)])
        except Exception:
            log.warning("memory update failed for %s", name, exc_info=True)
        finally:
            self.running.discard(user.id)

    def apply_json(self, d, data, names, her, lines, where="", took_part=True):
        changes, dropped = [], []
        theirs = "\n".join(t for w, t in lines if w == "them")
        hers = "\n".join(t for w, t in lines if w == "her")

        def source(quote, allow=("them", "other")):
            who = find_evidence(quote, lines) if quote else None
            return {"them": "said", "other": "heard", "her": "her"}.get(who) if who in allow else None

        profile = data.get("profile") if isinstance(data.get("profile"), dict) else {}
        for key, item in profile.items():
            slot = norm_slot(str(key))
            value, quote = (item.get("value"), item.get("evidence")) if isinstance(item, dict) else (item, None)
            if not slot or slot == "her_nick" or value in (None, "", []) or NON_ANSWER.match(str(value).strip()):
                continue
            value = str(value)
            src = (
                source(quote)
                if quote
                else ("said" if norm_text(value) and norm_text(value) in norm_text(theirs) else None)
            )
            if src is None:
                dropped.append(f"{slot}={value}")
                continue
            if slot == "age" and not re.search(
                r"\b" + re.escape(re.sub(r"\D", "", value) or "x") + r"\b", quote or theirs
            ):
                dropped.append(f"age={value} (the quote doesn't say it)")
                continue
            if slot == "nickname" and str(value).strip().lower() in {n.lower() for n in names[:1]}:
                continue
            if slot == "nickname" and not self._asked_for(value, theirs, her):
                log.info("ignored nickname %r for %s: they never asked for it", value, names[0] if names else "?")
                continue
            self._set_slot(d, slot, value, "asked" if slot == "nickname" else src, changes, quote)
        for f in data.get("new_facts") or []:
            if not isinstance(f, dict):
                continue
            text, quote = str(f.get("fact", "")), f.get("evidence")
            if her and re.match(r"^" + re.escape(her) + r"\b", text, re.I):
                continue
            src = source(quote)
            if src is None:
                dropped.append(text)
                continue
            cat = norm_cat(f.get("category"))
            tags = [t.strip().lower() for t in f.get("tags") or [] if isinstance(t, str) and t.strip()][:5]
            self._add_fact(
                d,
                text,
                cat,
                src,
                plan_date(f.get("date")) if cat == "plans" else None,
                changes,
                "F",
                names,
                quote,
                tags,
            )
        for f in data.get("changed_facts") or []:
            if isinstance(f, dict) and str(f.get("id", "")).lstrip("F").isdigit():
                fid = int(str(f["id"]).lstrip("F"))
                src = source(f.get("evidence"))
                if src is None:
                    dropped.append(f"change F{fid}: {f.get('fact', '')}")
                    continue
                old = self._find(d, fid)
                when = plan_date(f.get("date"))
                if old is not None and old.get("cat") == "plans" and old.get("when") and not when:
                    old.pop("when")
                self._update_fact(d, fid, str(f.get("fact", "")), when, changes, "F", names, src, f.get("evidence"))
        for w in data.get("wrong_facts") or []:
            fid, quote = (w.get("id"), w.get("evidence")) if isinstance(w, dict) else (w, None)
            if not str(fid).lstrip("F").isdigit():
                continue
            fid = int(str(fid).lstrip("F"))
            if source(quote, allow=("them",)) is None:
                dropped.append(f"forget F{fid}")
                continue
            self._forget_fact(d, fid, changes, "F", f"they said: {cut(clean_fact(quote), 60)}")
        nick = clean_name(data.get("her_nickname_for_them"))
        if (
            nick
            and nick.lower() not in {n.lower() for n in names[:1]}
            and "nickname" not in d["slots"]
            and nick.lower() not in PET_NAMES
            and nick.lower() != (her or "").lower()
            and (
                any(p.search(hers) for p in HER_NICK)
                or len(re.findall(r"(?<!\w)" + re.escape(nick) + r"(?!\w)", hers, re.I)) >= 2
            )
        ):
            self._set_slot(d, "her_nick", nick, "her", changes)
        calls = clean_name(data.get("their_name_for_her"))
        if (
            calls
            and calls.lower() != (her or "").lower()
            and re.search(r"(?<!\w)" + re.escape(calls) + r"(?!\w)", theirs, re.I)
        ):
            old = d.get("calls_her", {}).get("v")
            if (old or "").lower() != calls.lower():
                d["calls_her"] = {"v": calls, "t": time.time()}
                changes.append(f"+ calls her: {calls}" + (f" (was {old})" if old else ""))
        bond = whole(clean_fact(data.get("bond")), BOND_MAX)
        if bond and not NON_ANSWER.match(bond) and bond != d.get("bond"):
            d["bond"] = bond
            changes.append(f"♥ bond: {bond}")
        conv = data.get("conversation") if isinstance(data.get("conversation"), dict) else {}
        summary = whole(clean_fact(conv.get("summary") or data.get("topic")), SUMMARY_MAX)
        if took_part and summary and not NON_ANSWER.match(summary):
            e = self._current_episode(d)
            now = time.time()
            if e is None:
                e = {"id": d["next_eid"], "sid": d.get("session_start") or d.get("first_seen"), "t": now}
                d["next_eid"] += 1
                d["episodes"].append(e)
            e.update(
                summary=summary, mood=cut(clean_fact(conv.get("mood")), 60), u=now, where=where or e.get("where", "")
            )
            changes.append(f"💬 E{e['id']} {summary}")
        for text in data.get("new_threads") or []:
            text = cut(clean_fact(text), 140)
            open_ = [t for t in d["threads"] if not t.get("done")]
            if took_part and len(text) >= 8 and not any(similar(t["text"], text, 0.5) for t in open_):
                d["threads"].append({"id": d["next_tid"], "text": text, "t": time.time()})
                changes.append(f"↪ T{d['next_tid']} {text}")
                d["next_tid"] += 1
        for tid in data.get("done_threads") or []:
            t = next((t for t in d["threads"] if str(t["id"]) == str(tid).lstrip("T")), None)
            if t is not None and not t.get("done"):
                d["threads"].remove(t)
                changes.append(f"✓ T{t['id']} {t['text']}")
        if self.self_notes:
            for f in data.get("about_her") or []:
                if not isinstance(f, dict):
                    continue
                if source(f.get("evidence"), allow=("her",)) is None:
                    dropped.append(f"about her: {f.get('fact', '')}")
                    continue
                identity = getattr(self.app, "identity", None)
                if identity is not None and identity.wrong_fact(f.get("fact")):
                    changes.append(f"✗ not saved about herself, it's wrong: {cut(str(f.get('fact', '')), 80)}")
                    continue
                self._add_fact(
                    self.own,
                    str(f.get("fact", "")),
                    f.get("category"),
                    "said",
                    None,
                    changes,
                    "S",
                    quote=f.get("evidence"),
                )
        if dropped:
            changes.append("✗ no real quote, not saved: " + "; ".join(cut(str(x), 60) for x in dropped[:6]))
        self.dirty = True
        return changes

    def _should_reflect(self, d):
        if not self.notes or self.reflect_every <= 0:
            return False
        if len(d["facts"]) + len(d.get("episodes", [])) < 4:
            return False
        if self._must_reflect(d):
            return True
        if not d.get("portrait"):
            return d.get("since_reflect", 0) >= 2
        return d.get("since_reflect", 0) >= self.reflect_every or (
            d.get("since_reflect", 0) >= 2 and time.time() - d.get("reflect_at", 0) > 7 * DAY
        )

    def _must_reflect(self, d):
        return len(d["facts"]) > self.facts_max * 0.8 or len(d.get("episodes", [])) > self.episodes_max

    async def reflect_now(self, uid):
        d = self.get(uid)
        if not d or int(uid) in self.running or not self._should_reflect(d):
            return
        self.running.add(int(uid))
        name = d.get("name") or str(uid)
        try:
            changes = await self.reflect(d, name)
            self._evict(d, self.facts_max, changes)
            self.dirty = True
            if changes:
                log.info("%s: %s", name, " | ".join(changes))
                await self.log(f"**memory · {name}** (rethought while resting)\n" + "\n".join(changes))
            if self.embed.active:
                await self.embed.docs([text for _, _, text, _ in self._items(d)])
        finally:
            self.running.discard(int(uid))

    async def reflect(self, d, name):
        gpu.background()
        her = self.her_name()
        now = time.time()
        fold = d["episodes"][: -self.episodes_max] if len(d["episodes"]) > self.episodes_max else []
        facts = "\n".join(
            f"F{f['id']} [{f['cat']}] {f['text']}"
            + (" " + wording("memory.known_labels.reflect_heard") if unsure(f) else "")
            + (f" @{f['when']}" if f.get("when") else "")
            + f" ({said_ago(f['t'], now)})"
            for f in sorted(d["facts"], key=lambda f: f["id"])
        )
        episodes = "\n".join(
            f"E{e['id']} ({said_ago(e.get('u', e['t']), now)}"
            + (f", {e['where']}" if e.get("where") else "")
            + "): "
            + e["summary"]
            + (f" [{e['mood']}]" if e.get("mood") else "")
            for e in d["episodes"]
        )
        prev = []
        if d.get("portrait"):
            prev.append(f"portrait: {d['portrait']}")
        if d.get("talk_style"):
            prev.append(f"talk_style: {d['talk_style']}")
        for kind in ("jokes", "avoid", "shared"):
            for j in d.get(kind) or []:
                prev.append(f"{kind}: {j['text']} (from {', '.join(j.get('from', []))})")
        act = activity.summary(d, now)
        system = say(
            "memory.reflect_system",
            her=her,
            history=wording("memory.reflect_history_fold") if fold else wording("memory.reflect_history_none"),
        )
        feelings = getattr(self.app, "feelings", None)
        feel = feelings.summary(d) if feelings is not None else ""
        pinned = ""
        if d.get("rel") or d.get("pinned"):
            pinned = (
                say(
                    "memory.reflect_pinned",
                    name=name,
                    rel=d.get("rel") or wording("memory.reflect_rel_unknown"),
                    pinned=d.get("pinned") or "",
                )
                + "\n\n"
            )
        none = wording("memory.reflect_none")
        user_text = (
            say("memory.reflect_intro", her=her, name=name)
            + "\n\n"
            + pinned
            + say("memory.reflect_profile", profile=self.slot_summary(d) or wording("memory.reflect_nothing"))
            + "\n"
            + (say("memory.reflect_bond", bond=d["bond"]) + "\n" if d.get("bond") else "")
            + (say("memory.reflect_feelings", feelings=feel) + "\n" if feel else "")
            + (say("memory.reflect_discord", activity=act) + "\n" if act else "")
            + (
                say("memory.reflect_own_profile", profile=self.profile_line(d, name)) + "\n"
                if d.get("discord_profile")
                else ""
            )
            + "\n"
            + say("memory.reflect_facts", facts=facts or none, episodes=episodes or none)
            + "\n"
            + (
                "\n" + say("memory.reflect_fold", episodes=", ".join("E" + str(e["id"]) for e in fold)) + "\n"
                if fold
                else ""
            )
            + ("\n" + say("memory.reflect_old_history", history=d["history"]) + "\n" if d.get("history") else "")
            + ("\n" + wording("memory.reflect_last_time") + "\n" + "\n".join(prev) + "\n" if prev else "")
            + "\n"
            + (wording("memory.reflect_think") if self.think_on else wording("memory.reflect_json_only"))
        )

        changes = []
        self.reflecting.add(id(d))
        try:
            out = (await self.app.helper.ask(system, user_text, REFLECT, REFLECT_TOKENS, think=True)).text
        except Exception:
            log.warning("memory reflect failed for %s", name, exc_info=True)
            return []
        finally:
            self.reflecting.discard(id(d))
        data = parse_json(out)
        if not data:
            log.info("%s: reflecting gave nothing usable", name)
            return []
        valid = {f"F{f['id']}" for f in d["facts"]} | {f"E{e['id']}" for e in d["episodes"]}
        portrait = whole(clean_fact(data.get("portrait")), PORTRAIT_MAX)
        if portrait and not NON_ANSWER.match(portrait) and portrait != d.get("portrait"):
            d["portrait"] = portrait
            changes.append(f"🪞 portrait: {portrait}")
        style = whole(clean_fact(data.get("talk_style")), STYLE_MAX)
        if style and not NON_ANSWER.match(style) and style != d.get("talk_style"):
            d["talk_style"] = style
            changes.append(f"🗣 with them: {style}")
        for kind, label in (("inside_jokes", "jokes"), ("avoid", "avoid"), ("shared", "shared")):
            kept = []
            for j in data.get(kind) or []:
                if not isinstance(j, dict):
                    continue
                refs = [str(r).upper().strip() for r in j.get("from") or []]
                text = cut(clean_fact(j.get("text")), 140)
                if text and any(r in valid for r in refs):
                    kept.append({"text": text, "from": [r for r in refs if r in valid], "t": now})
            if [k["text"] for k in kept] != [k["text"] for k in d.get(label) or []]:
                d[label] = kept
                if kept:
                    changes.append(f"✦ {label}: " + "; ".join(k["text"] for k in kept))
        for m in data.get("merge") or []:
            if isinstance(m, dict):
                self._merge_facts(
                    d,
                    [int(i) for i in m.get("ids") or [] if str(i).isdigit()],
                    str(m.get("fact", "")),
                    changes,
                    "F",
                    self._names_of(d),
                )
        for fid in data.get("forget") or []:
            if str(fid).isdigit():
                self._forget_fact(d, int(fid), changes, "F", "outdated (reflecting)")
        history = whole(clean_fact(data.get("history")), HISTORY_MAX)
        if fold and history and not NON_ANSWER.match(history):
            d["history"] = history
            ids = {e["id"] for e in fold}
            d["episodes"] = [e for e in d["episodes"] if e["id"] not in ids]
            changes.append(f"📜 folded {len(ids)} old conversations into: {history}")
        elif fold and len(d["episodes"]) > 2 * self.episodes_max:
            d["episodes"] = d["episodes"][-2 * self.episodes_max :]
        d["since_reflect"], d["reflect_at"] = 0, now
        self.fix_voice_of(d)
        self.dirty = True
        return changes
