import asyncio
import datetime as dt
import json
import re
import time

from mitski.core import logs
from mitski.core.text import cut
from mitski.llm import gpu
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
NOTES_SCHEMA = {
    **SCHEMA,
    "properties": {**SCHEMA["properties"], "feelings": {"type": "array", "maxItems": 5, "items": FEELING_ITEM}},
    "required": [*SCHEMA["required"], "feelings"],
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
        lines = []
        for key in list(SLOTS) + ["her_nick"]:
            v = self._slot_value(d, key)
            if v is not None:
                label = "nickname she gave them" if key == "her_nick" else key
                lines.append(f"{label}: {v}" + (" (only heard from someone else)" if unsure(d["slots"][key]) else ""))
        for f in sorted(d["facts"], key=lambda f: f["id"]):
            lines.append(
                f"F{f['id']} [{f['cat']}] "
                + f["text"]
                + (" (only heard from someone else, not confirmed)" if unsure(f) else "")
                + (f" (date {f['when']})" if f.get("when") else "")
            )
        if d.get("rel"):
            lines.append(f"who they are to her (set by hand, always true): {d['rel']}")
        if d.get("pinned"):
            lines.append(f"set by hand, always true: {d['pinned']}")
        if d.get("bond"):
            lines.append(f"bond: {d['bond']}")
        return "\n".join(lines) or "(nothing yet)"

    def _instructions(self, her):
        today = dt.date.today()
        yesterday = today - dt.timedelta(days=1)
        monday = today + dt.timedelta(days=(7 - today.weekday()) or 7)
        example = {
            "profile": {
                "age": {"value": "18", "evidence": "i turned 18 yesterday"},
                "birthday": {
                    "value": f"{MONTHS[yesterday.month - 1]} {yesterday.day}",
                    "evidence": "i turned 18 yesterday",
                },
            },
            "new_facts": [
                {
                    "category": "plans",
                    "fact": "has an exam",
                    "tags": ["exam", "school", "test"],
                    "evidence": "got an exam on monday tho ugh",
                    "date": monday.isoformat(),
                },
                {
                    "category": "people",
                    "fact": "has a little sister",
                    "tags": ["sister", "family", "sibling"],
                    "evidence": "alex has a little sister btw",
                },
            ],
            "changed_facts": [
                {"id": 1, "fact": "quit valorant, plays deadlock now", "evidence": "i quit valorant its so bad now"},
                {"id": 2, "fact": "has a cat named mochi", "evidence": "my cat's name is mochi not miso lol"},
            ],
            "wrong_facts": [],
            "her_nickname_for_them": "",
            "their_name_for_her": "doll",
            "bond": "",
            "conversation": {
                "summary": "alex turned 18 and switched from valorant to deadlock. you mixed up "
                "his cat's name and he teased you for being older",
                "mood": "playful",
            },
            "new_threads": ["ask alex how his exam on monday went"],
            "done_threads": [],
            "about_her": [{"category": "life", "fact": "is 20 years old", "evidence": "i'm 20 btw"}],
            "feelings": [
                {
                    "kind": "friendly_teasing",
                    "intensity": 1,
                    "evidence": "ok doll whatever u say",
                    "why": "teased you back about being older",
                }
            ],
        }
        return f"""You keep {her}'s memory of the people she talks to on discord. You get what she already knows about one person and their newest messages. Answer with JSON only, saying what's new or changed about that person.

Be careful about who is who: the person is the one in "Known about", {her} is her, everyone else is someone else. Names and pet names they use for {her} ("hey doll", "thanks babe") are NOT their nickname, those go in their_name_for_her.

Everything you write is {her}'s own memory, so she reads it about herself: wherever {her} comes up, write "you" and "your", never her name or she/her ("you mixed up his cat's name", "only plays with your group"). The only exception is "evidence", which is copied word for word.

People sometimes talk about {her} as a bot or an AI ("the bot", "the ai", "wheeler's bot", "his bot", "she's an ai"), or about how she works (her code, her memory, her persona, her vc or typing sounds, her profile). All of that is about {her}, not about anyone else and not about someone's girlfriend or friend: never turn it into a fact about the person ("has a bot", "his girlfriend's vc plays asmr"), and leave it out of summaries. Never call {her} a bot or an AI in anything you write.

EVIDENCE: every profile field, fact, change and correction needs "evidence": the exact words from the messages it comes from, copied word for word (a short piece of one message is fine), and those words have to actually say it (not just be a message from around then). It gets checked against the chat, and anything that isn't really in there is thrown away. So only write down what someone actually said. Never guess, never fill in details nobody said, never mix up who said what. Something someone ELSE says about the person counts too (quote them), {her} will treat it as hearsay. Pictures show up as [image: ...]: you can learn from them (like their dog) only if they say it's theirs.

profile: only the fields the new messages tell you ({", ".join(f"{k} = {v}" for k, v in SLOTS.items())}), each as {{"value": ..., "evidence": ...}}. A new value replaces the old one. Leave out fields that weren't mentioned.
new_facts: new things worth remembering later. what they like, play, watch, listen to, do, their friends, family and pets, things that happened to them, how they are. Short, about them, without their name ("plays cs2 every night"). tags: 2 to 5 lowercase words to find it again later, including broader ones (a fact about a golden retriever gets "dog", "pet"). For plans add "date" as YYYY-MM-DD if you can work it out (today is {today.strftime("%A")} {today.isoformat()}).
changed_facts: known facts (by number) that changed or were a bit wrong, rewritten so they're true now (with a new "date" if a plan moved).
wrong_facts: known facts that turned out false, aren't true anymore, or that they asked {her} to forget, as {{"id": number, "evidence": what they said}}.
her_nickname_for_them: a real nickname {her} gave them (like "from now on ur bean"), not a pet name like babe or doll, otherwise "".
their_name_for_her: what they call {her}, if they used a name or pet name for her (doll, babe, a nickname), otherwise "".
profile.nickname: only if THEY said they want to be called something ("call me will", "i go by will").
bond: one sentence on how they and {her} get along, written to her ("you tease each other a lot"), only if that changed, otherwise "".
conversation: if {her} talked with them in these messages: summary = 1 or 2 sentences on what you two talked about and anything that happened between you, written to {her} as "you" so she can remember it later (if "This conversation so far" has a summary, write the updated one for the whole conversation). mood = a few words on how it went. Both "" if {her} wasn't part of it.
new_threads: things to come back to in a later chat, written as a note to {her}: something she promised, something they'll tell her later, something she should ask about ("ask how the date went", "you said you'd send him the song"). Not plans with a date (those are facts). Usually none.
done_threads: numbers of open threads (T) that got dealt with in these messages.
about_her: things {her} said about HERSELF (her age, life, likes, past, plans), with her own words as evidence, so she stays consistent. Start with the verb ("is 20 years old", "plays cs2") and say "your" for what's hers ("your pc keeps freezing"). Nothing about whether she's a bot, an AI or a real person.
feelings: how the person treated {her} in the new messages, so she can feel about them the way a person would. ONLY messages marked "(to {her})" count: those were said to her. Anything they said to someone else or to the room never counts, however nice or mean, even if it's about {her}. The one exception is mean_to_her_friends, from a message marked "(to <name>)" going after that person. Each moment is one from this list:
{FEELING_KINDS}
intensity: 1 = a small thing, 2 = clear, 3 = a big deal. why: a few words to {her} about what they did ("called you annoying", "hyped your cs clip", "loves laufey like you do"). evidence: their exact words, as always. Tell banter from meanness: friends roasting each other with "lol", emojis and both laughing is friendly_teasing, not insulted_her. Sarcasm isn't a compliment, and being nice once isn't genuine_affection. shared_interest only when they like something {her} likes too (her own facts and what she said show what she likes). Most messages have none of this: an empty list is normal.

Only write down lasting things worth knowing next week. Not what they just did in this chat ("said hi", "used 'meow'", "sent a gif", "asked about x"), not emojis, and not how they feel right this moment ("is tired", "is frustrated"). Skip jokes, sarcasm and obvious trolling. Don't repeat what's already known. Empty lists are fine, most messages have nothing new.

Example. Known about alex:
age: 17
F1 [games] plays valorant
F2 [life] has a cat named miso
New messages:
alex: i turned 18 yesterday!! also i quit valorant its so bad now
{her}: happy late birthday!! what are u playing now
alex: deadlock mostly. got an exam on monday tho ugh
alex: and my cat's name is mochi not miso lol
sam: alex has a little sister btw
{her}: mochi!! im sorry 😭 i'm 20 btw so ur still a baby
alex: ok doll whatever u say
Answer:
{json.dumps(example, ensure_ascii=False)}"""

    def _data_text(self, d, name, her, earlier, new, line, think=False):
        now = time.time()
        text = f"Known about {name}:\n{self._known_text(d)}\n"
        threads = [t for t in d.get("threads", []) if not t.get("done")]
        if threads:
            text += (
                f"\nOpen threads with {name}:\n"
                + "\n".join(f"T{t['id']} {t['text']} ({said_ago(t['t'], now)})" for t in threads)
                + "\n"
            )
        past = self._last_episodes(d, 3, now)
        if past:
            text += (
                f"\nTheir last conversations with {her}:\n"
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
            text += f"\nThis conversation so far: {current['summary']}\n"
        if self.self_notes and self.own["facts"]:
            own = sorted(self.own["facts"], key=lambda f: -f["id"])[:25]
            text += (
                f"\nThings {her} already said about herself:\n"
                + "\n".join(f"S{f['id']} [{f['cat']}] {f['text']}" for f in sorted(own, key=lambda f: f["id"]))
                + "\n"
            )
        if earlier:
            text += "\nEarlier messages (already noted, only for context):\n" + "\n".join(map(line, earlier)) + "\n"
        text += "\nNew messages:\n" + "\n".join(map(line, new)) + "\n\n"
        if think:
            text += (
                f"First think it through: go over the new messages one by one. Who wrote it, and is it about "
                f"{name}, {her} or someone else? Is it lasting, or just chat? Is it already known, or does it "
                f"correct something known? What are the exact words to quote? And how did {name} treat {her}: "
                f"kind, mean, banter, flirty, something in common? Then answer with the JSON."
            )
        else:
            text += f"What's new or changed about {name}? JSON only."
        return text

    def _aimed(self, user, msgs, me):
        """Who each of the person's messages was really said to, decided by code: "them" = to her, "them_friend" =
        to someone she's close to, "them_else" = to anyone else or the room. Her own are "her", others' "other"."""
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

            while len(new) > 1 and sum(len(line(m)) + 1 for m in new) > NOTES_CHAT_CHARS:
                new = new[1:]

            def who(m):
                return "her" if m.author.id == me else "them" if m.author.id == user.id else "other"

            evidence = [(who(m), self.text_of(m)) for m in earlier + new]
            to_her = [(aimed.get(m.id, ("other", None))[0], self.text_of(m)) for m in earlier + new]
            where = f"#{channel.name}" if getattr(channel, "name", None) else "dms"
            took_part = any(m.author.id == me for m in new)
            answer = await self.app.helper.ask(
                self._instructions(her),
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
                self.fix_voice_of(d)
                self.fix_own_voice()
            self._expire(d, changes)
            d["since_reflect"] = d.get("since_reflect", 0) + sum(1 for c in changes if not c.startswith("✗"))
            d["notes_upto"] = max(m.id for m in new)
            d["since_notes"], d["heard"], d["disclosed"], d["notes_at"] = 0, 0, False, time.time()
            if self._should_reflect(d):
                changes += await self.reflect(d, name)
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
        if len(d["facts"]) > self.facts_max * 0.8 or len(d.get("episodes", [])) > self.episodes_max:
            return True
        if not d.get("portrait"):
            return d.get("since_reflect", 0) >= 2
        return d.get("since_reflect", 0) >= self.reflect_every or (
            d.get("since_reflect", 0) >= 2 and time.time() - d.get("reflect_at", 0) > 7 * DAY
        )

    async def reflect(self, d, name):
        gpu.background()
        her = self.her_name()
        now = time.time()
        fold = d["episodes"][: -self.episodes_max] if len(d["episodes"]) > self.episodes_max else []
        facts = "\n".join(
            f"F{f['id']} [{f['cat']}] {f['text']}"
            + (" (heard from others, not confirmed)" if unsure(f) else "")
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
        system = (
            f"You help {her} understand a person she knows from discord, from everything she remembers about "
            f'them. Write to her: {her} is always "you" and "your", never her name or she/her ("one of your server '
            f'friends", not "one of {her}\'s server friends"). Use ONLY what\'s listed: no guessing, nothing invented, no '
            f"psychoanalysing. {her} is a real girl to everyone: if anything listed talks about her as a bot or "
            f'an AI ("his bot", "the ai"), it\'s people joking about her, so leave it out and never call her '
            f"that. Answer with JSON.\n\n"
            f"portrait: 2 to 4 sentences on who they are and what matters to them right now, and what they are "
            f'to her. Things only heard from others stay "apparently".\n'
            f'talk_style: 1 or 2 sentences on how you are with them and what they like from you ("you tease them '
            f'and they love it", hype, being there for them, gaming talk, ...), going by how your chats went and '
            f"fitting how you feel about them.\n"
            f"inside_jokes: running jokes or bits between them, only if the episodes or facts show one. "
            f"avoid: things that upset them or that they don't want to talk about, only if shown. "
            f'shared: things they and {her} have in common or did together. For all three, "from" lists the '
            f"F/E numbers it comes from. Empty lists are fine.\n"
            f"merge: facts that say the same thing or belong together, as one fact. forget: facts that are "
            f"contradicted by a newer one (higher number = newer), outdated, or too trivial to keep.\n"
            "history: "
            + (
                "a short summary (max 3 sentences) of the episodes marked OLD plus the old history, "
                "so they can be dropped: how long they've known each other and what they went "
                "through together."
                if fold
                else '"" (nothing to fold yet)'
            )
        )
        user_text = (
            f"Everything {her} remembers about {name}.\n\n"
            + (
                f"Set by hand, always true, everything you write has to fit it: "
                f"{name} is {d.get('rel') or 'someone she knows'}. {d.get('pinned') or ''}\n\n"
                if d.get("rel") or d.get("pinned")
                else ""
            )
            + f"Profile: {self.slot_summary(d) or '(nothing)'}\n"
            + (f"Bond: {d['bond']}\n" if d.get("bond") else "")
            + (
                f"How you feel about them right now: {self.app.feelings.summary(d)}\n"
                if getattr(self.app, "feelings", None) is not None and self.app.feelings.summary(d)
                else ""
            )
            + (f"On discord: {act}\n" if act else "")
            + f"\nFacts:\n{facts or '(none)'}\n\nConversations (episodes):\n{episodes or '(none)'}\n"
            + (f"\nOLD (fold these into history): {', '.join('E' + str(e['id']) for e in fold)}\n" if fold else "")
            + (f"\nOld history: {d['history']}\n" if d.get("history") else "")
            + ("\nWhat you wrote last time (keep what's still right):\n" + "\n".join(prev) + "\n" if prev else "")
            + ("\nThink it through first, then answer with the JSON." if self.think_on else "\nJSON only.")
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
