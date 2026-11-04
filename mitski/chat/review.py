from mitski.brain.answers import answers_it
from mitski.chat import convo
from mitski.chat.messages import short_name
from mitski.core import logs
from mitski.core.component import Component
from mitski.core.metrics import Metrics
from mitski.core.text import cut

log = logs.get("review")


class DraftReview(Component):
    async def answer_all(self, turns, persona, notes, things, channel, others, seen, first):
        asked = " / ".join(f'"{cut(t.text, 120)}"' for t in things)
        must = f"Answer each of these now, one short line for each, in your own words: {asked}"
        text = await self.llm.generate(
            self.llm.fmt_inline.chat(persona, turns, notes + "\n" + must),
            temperature=min(self.cfg.TEMPERATURE, 0.6),
            lora_scale=self.cfg.LORA_SCALE * self.cfg.ANSWER_RETRY_LORA,
        )
        lines = self.app.drafts.tidy(text, channel.id, others)
        return lines if len(lines) > len(first) and not self.app.drafts.problem(lines, seen) else first

    async def match_answers(self, lines, things):
        """Which message each line answers, None for a line that answers none of them (like "hey anna!").

        She doesn't answer in the order they asked, skips things, and sends extra lines, so none of it can be assumed.
        Returns None unless it's clear, and then the caller doesn't aim at any one message.
        """
        n, count = len(things), len(lines)
        schema = {
            "type": "object",
            "properties": {
                "answers": {
                    "type": "array",
                    "minItems": count,
                    "maxItems": count,
                    "items": {"type": "integer", "minimum": 0, "maximum": n},
                }
            },
            "required": ["answers"],
            "additionalProperties": False,
        }
        asked = "\n".join(f"{i}. {cut(t.text, 160)}" for i, t in enumerate(things, 1))
        said = "\n".join(f"- {cut(ln, 160)}" for ln in lines)
        out = await self.app.helper.ask_json(
            'You match replies in a chat to the questions they answer. Answer with JSON: {"answers": [numbers]}.',
            f"Questions:\n{asked}\n\nReplies, in order:\n{said}\n\nFor each reply, in order, the number of the "
            f"question it answers. 0 if it doesn't answer any of them, like a greeting or a remark. A short reply can "
            f'still be an answer: "cs2" answers what game they play, "portugal" answers where they live. A reply can '
            f"be about the same question as another one, and a question doesn't have to be answered at all.",
            schema,
            20 + 6 * count,
        )
        answers = (out or {}).get("answers")
        if (
            not isinstance(answers, list)
            or len(answers) != count
            or not all(isinstance(i, int) and 0 <= i <= n for i in answers)
            or not any(answers)
        ):
            return None
        return [things[i - 1].msg if i else None for i in answers]

    def authors_after(self, channel, msg_id, to_id=None):
        seen = {}
        for mid, uid in self.state.chan_log.get(channel.id, ()):
            if mid > msg_id:
                seen[mid] = uid
        for m in self.state.last_history.get(channel.id, []):
            if m.id > msg_id:
                seen.setdefault(m.id, m.author.id)
        me = self.me.id
        return [
            uid if uid != me or self.state.addressed.get(mid, to_id) == to_id else -1
            for mid, uid in sorted(seen.items())
        ]

    async def check(self, lines, anchor, msgs, around):
        pool = sorted({m.id: m for m in list(msgs)[-12:] + list(around) + [anchor]}.values(), key=lambda m: m.id)[-15:]
        if anchor not in pool:
            pool = pool[1:] + [anchor]
            pool.sort(key=lambda m: m.id)
        if len({m.author.id for m in pool if m.author.id != self.me.id}) < 2 and not any(
            m.author.id == self.me.id and self.state.addressed.get(m.id) not in (None, anchor.author.id) for m in pool
        ):
            return None, None, False
        if not self.cfg.ADDRESSEE_CHECK:
            latest = {}
            for m in pool:
                if m.author.id not in (self.me.id, anchor.author.id):
                    for n in (short_name(m.author), self.messages.call(m.author)):
                        latest[n.lower()] = m
            named = convo.named_first(lines, latest)
            return ("other", named, False) if named is not None else (None, None, False)
        by_id = {m.id: m for m in pool}
        numbered = [(self.messages.label(m, by_id), cut(self.messages.text(m), 200)) for m in pool]
        meant = pool.index(anchor) + 1
        system, ask = convo.check_request(
            short_name(self.me), numbered, cut(" / ".join(lines), 400), meant, numbered[meant - 1][0]
        )
        verdict, i, mixed = convo.parse_check(
            await self.app.helper.ask_json(system, ask, convo.CHECK, 40), len(pool), meant
        )
        if verdict != "other":
            return verdict, None, mixed
        m = pool[i]
        if m.author.id == anchor.author.id:
            return "fits", None, mixed
        if m.author.id == self.me.id:
            to = self.state.addressed.get(m.id)
            if to == anchor.author.id:
                return "fits", None, mixed
            theirs = [x for x in pool if x.author.id == to and x.id < m.id] if to else []
            return ("other", theirs[-1], mixed) if theirs else ("general", None, mixed)
        return "other", m, mixed

    def already_answered(self, m):
        me = self.me.id
        for mid, uid in self.state.chan_log.get(m.channel.id, ()):
            if uid == me and mid > m.id and self.state.addressed.get(mid) == m.author.id:
                return True
        for x in self.state.last_history.get(m.channel.id, []):
            if (
                x.author.id == me
                and x.id > m.id
                and (self.state.addressed.get(x.id) == m.author.id or (x.reference and x.reference.message_id == m.id))
            ):
                return True
        return False

    async def refocus(self, turns, persona, notes, anchor, burst, thought, channel, others, seen):
        name = self.messages.call(anchor.author)
        must = (
            f'Reply to {name} now, to what {name} said: "{cut(self.app.addressing.burst_text(burst), 240)}". Answer {name}\'s message, '
            f"not anyone else's, and not something you already answered. If {name} is reacting to something you said, "
            f"it was you who said it (see what you said lately above): own it, don't flip it around."
        )
        text = await self.llm.generate(
            self.llm.fmt_inline.chat(persona, turns, notes + "\n" + must), temperature=min(self.cfg.TEMPERATURE, 0.7)
        )
        lines = self.app.drafts.tidy(text, channel.id, others)
        if not lines or self.app.drafts.problem(lines, seen):
            return None
        if thought.wants_answer and not answers_it(lines, thought.brief, thought.checked):
            return None
        return lines

    async def make_her_answer(self, turns, persona, notes, thought, target, msgs, channel, others, seen, first, mode):
        name = self.messages.call(target.author)
        must = f"Answer {name} now, in your own words: {thought.brief.rstrip('.')}."
        prompt = self.llm.fmt_inline.chat(persona, turns, notes + "\n" + must)
        text = await self.llm.generate(
            prompt,
            temperature=min(self.cfg.TEMPERATURE, 0.6),
            lora_scale=self.cfg.LORA_SCALE * self.cfg.ANSWER_RETRY_LORA,
        )
        retry = self.app.drafts.tidy(text, channel.id, others)
        if retry and answers_it(retry, thought.brief, thought.checked) and not self.app.drafts.problem(retry, seen):
            log.info(
                "[%s] answered on the second try (lora at %g)", mode, self.cfg.LORA_SCALE * self.cfg.ANSWER_RETRY_LORA
            )
            return retry
        Metrics.event("answer rewrite")
        her = short_name(self.me)
        examples = [self.messages.text(m) for m in msgs if m.author.id == self.me.id and self.messages.text(m)][-8:]
        recent = "\n".join(
            f"{her if m.author.id == self.me.id else self.messages.call(m.author)}: {cut(self.messages.text(m), 200)}"
            for m in list(msgs)[-8:]
        )
        out = await self.llm.generate(
            self.llm.fmt.instruct(
                f"You write {her}'s next message in a discord chat, exactly in her style: {self.cfg.PERSONA} It's a casual "
                f"chat message, so it never sounds like an assistant.",
                f"Recent chat:\n{recent}\n\n"
                + (
                    "How she types (her own recent messages):\n" + "\n".join(f"- {e}" for e in examples) + "\n\n"
                    if examples
                    else ""
                )
                + f"Write her reply to {name}. It has to tell them this: {thought.brief}\n"
                f"She's the one talking, so she says i, me and my about herself, never {her} or she/her. "
                f"1 or 2 short, casual lines, like her examples. {self.cfg.STYLE_NOTE} Just the message, nothing else.",
            ),
            temperature=0.7,
            n_predict=120,
            helper=True,
        )
        written = self.app.drafts.tidy(out, channel.id, others)
        if (
            written
            and answers_it(written, thought.brief, thought.checked)
            and not self.app.drafts.problem(written, seen)
        ):
            log.info("[%s] answered on the third try (written by the plain model in her style)", mode)
            return written
        log.info("[%s] couldn't get an answer out of her, sending her first reply", mode)
        return first
