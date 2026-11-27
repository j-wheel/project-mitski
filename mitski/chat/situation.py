from datetime import timedelta

import discord

from mitski.chat import guard
from mitski.chat.messages import clean, short_name
from mitski.chat.patterns import JUST_HI
from mitski.core.clock import time_phrase
from mitski.core.component import Component
from mitski.core.text import cut
from mitski.core.texts import say, wording


class Situation(Component):
    def minors_among(self, users):
        return self.app.ages.any_minor(users)

    def persona(self, user, guild=None, full=True, channel=None, people=()):
        policy = self.app.policy
        parts = [
            policy.tamed(channel, self.cfg.PERSONA),
            self.cfg.identity_note.replace("{name}", short_name(self.me) if self.me else "mitski"),
        ]
        facts = self.app.identity.line()
        if facts:
            parts.append(facts)
        blocking = self.app.blocking.note()
        if blocking:
            parts.append(blocking)
        parts.append(guard.STAY_A_PERSON)
        for blurb in (
            policy.tamed(channel, self.memory.blurb(user, full=full)),
            policy.tamed(channel, self.app.servers.blurb(guild)) if guild is not None else "",
            self.memory.self_blurb(),
            self.app.profiles.own_status(),
            self.app.emojis.hint(guild),
        ):
            if blurb:
                parts.append(blurb)
        parts.append(policy.note(channel, minors=self.minors_among([user, *people])))
        return "\n\n".join(parts)

    def notes(self, mode, channel, target, msgs, extras=(), around=(), burst=None):
        user = getattr(target, "author", None)
        her_id = self.me.id
        recent = list(msgs)[-12:]
        context = "\n".join(self.messages.text(m) for m in recent[-6:])
        people = []
        for m in reversed(recent):
            if m.author.id not in {her_id, getattr(user, "id", None)} | {p.id for p in people} and not m.author.bot:
                people.append(m.author)
        call = self.messages.call(user) if user is not None else None
        guild = getattr(channel, "guild", None)
        lines = [wording("chat.notes_header"), time_phrase(self.app.clock.now())]

        if isinstance(channel, discord.DMChannel):
            lines.append(say("chat.in_dms_with", name=call) if call else wording("chat.in_dms"))
        else:
            where = f"#{channel.name}" + ((" " + say("chat.on_server", server=guild.name)) if guild else "")
            who = (
                (" " + say("chat.with_name", name=call))
                + (f", {', '.join(self.messages.call(p) for p in people[:4])}" if people else "")
                if call
                else ""
            )
            lines.append(say("chat.chatting_in", where=where, who=who))
        if mode == "ambient":
            lines.append(wording("chat.joining_in"))
        elif mode == "dm_open":
            lines.append(say("chat.starting_dm", name=call))

        burst = [m for m in (burst or [target]) if m is not None]
        if guild is not None and user is not None and mode != "dm_open":
            mine = self.her_lately(channel, before=burst[0].id if burst else None)
            if mine:
                seen_msgs = list(msgs) + list(around)
                lines.append(
                    (wording("chat.her_recent_lines") + " ")
                    + " | ".join(
                        (
                            say("chat.her_line_to", name=self.messages.name_of_id(to, seen_msgs))
                            if to and self.messages.name_of_id(to, seen_msgs)
                            else wording("chat.her_line_to_chat")
                        )
                        + f': "{cut(self.messages.text(m), 90)}"'
                        for m, to in mine
                    )
                    + "."
                )
                last_mine = mine[-1][0]
                first = burst[0] if burst else target
                ref = first.reference.resolved if getattr(first, "reference", None) else None
                to_mine = isinstance(ref, discord.Message) and ref.author.id == her_id
                if to_mine or (
                    not isinstance(ref, discord.Message)
                    and first.author.id not in {t for _, t in mine if t}
                    and (first.created_at - last_mine.created_at).total_seconds() < 180
                ):
                    lines.append(say("chat.reacting_to_her", name=call))
        if user is not None and mode != "dm_open":
            if len(burst) > 1:
                lines.append(say("chat.several_messages", name=call))
            if people:
                said = cut(self.app.addressing.burst_text(burst), 200)
                to = ""
                ref = target.reference.resolved if getattr(target, "reference", None) else None
                if isinstance(ref, discord.Message) and ref.author.id not in (user.id,):
                    to = (
                        (" " + wording("chat.marked_to_you"))
                        if ref.author.id == her_id
                        else (" " + wording("chat.marked_to_someone"))
                        if ref.author.id in self.cfg.ignored
                        else (" " + say("chat.marked_to", name=self.messages.call(ref.author)))
                    )
                lines.append(say("chat.answering", name=call, to=to, message=said))
            nick = self.memory.call_name(user)
            if nick:
                lines.append(
                    say("chat.you_call_them", nickname=nick)
                    + (
                        say("chat.not_their_name", name=short_name(user))
                        if nick.lower() != short_name(user).lower()
                        else ""
                    )
                    + "."
                )
        d = self.memory.get(user.id) if user is not None else None
        age = self.memory.current_age(d) if d is not None else None
        if user is not None and self.app.ages.is_minor(user):
            told = (
                say("chat.minor_is", age=age)
                if age is not None and age < 18
                else say("chat.minor_is", age=self.app.ages.describe(user) or "under 18")
            )
            lines.append(say("chat.minor", name=call, age=told))
        if d is not None:
            known = self.memory.slot_summary(d)
            if known:
                lines.append(say("chat.already_know", name=call, known=known))
        hooks = self.memory.hooks(user, context) if user is not None else []
        if hooks:
            lines.append((wording("chat.on_your_mind") + " ") + "; ".join(hooks) + ".")
        for blurb in (
            self.memory.others_blurb(people, context),
            self.app.profiles.blurb(user, guild),
            self.app.knowledge.note(context),
            self.app.reacted.note(channel.id),
        ):
            if blurb:
                lines.append(blurb)
        if guild is not None and mode != "ambient" and self.app.away.just_woke(guild.id):
            lines.append(wording("chat.back_from_away"))
        if guild is not None and mode != "ambient" and self.app.away.just_released(guild.id):
            lines.append(wording("chat.can_talk_again"))
        doing = self.app.routine.note(getattr(guild, "id", None))
        if doing:
            lines.append(doing)
        mood = self.app.feelings.mood_note()
        if mood:
            lines.append(mood)
        if around:
            by_id = {m.id: m for m in list(msgs) + list(around)}
            lines.append(
                (say("chat.said_while_reading", name=call) + " ")
                + " | ".join(
                    f"{'you' + self.messages.label(m, by_id)[len(short_name(self.me) + ' (her)') :] if m.author.id == her_id else self.messages.call(m.author)}"
                    f": {cut(self.messages.text(m), 90)}"
                    for m in around
                )
                + "."
            )
            if any(m.author.id == her_id for m in around):
                lines.append(say("chat.already_said_there", name=call))
        if guild is not None:
            vc_line = self.app.voice.note(guild, lambda u: self.messages.call(u))
        else:
            vc_line = self.app.voice.call_note(channel, lambda u: self.messages.call(u))
        if vc_line:
            lines.append(vc_line)
        if target is not None and self.app.voice.decision_note(target.id):
            lines.append(self.app.voice.decision_note(target.id))
        lines += [e for e in extras if e]
        said = " / ".join(clean(self.messages.with_mentions(m)) for m in burst) if target is not None else ""
        just_hi = target is not None and all(JUST_HI.match(clean(self.messages.with_mentions(m))) for m in burst)
        if mode in ("direct", "dm") and just_hi:
            lines.append(say("chat.just_hi", name=call))
        elif mode in ("direct", "dm", "ambient") and said and len(said) < 25 and "?" not in said and not any(extras):
            lines.append(wording("chat.short_message"))
        if self.cfg.STYLE_NOTE:
            lines.append(self.cfg.STYLE_NOTE)
        reminder = self.app.policy.reminder(channel)
        if reminder:
            lines.append(reminder)
        lines.append(wording("chat.notes_footer"))
        return "\n".join(lines)

    def her_lately(self, channel, before=None, minutes=10, n=4):
        cutoff = discord.utils.utcnow() - timedelta(minutes=minutes)
        mine = [
            m
            for m in self.state.last_history.get(channel.id, [])
            if m.author.id == self.me.id and m.created_at > cutoff and (before is None or m.id < before)
        ]
        return [(m, self.state.addressed.get(m.id)) for m in reversed(mine[:n])]
