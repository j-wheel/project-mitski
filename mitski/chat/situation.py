from datetime import timedelta

import discord

from mitski.chat.messages import clean, short_name
from mitski.chat.patterns import JUST_HI
from mitski.core.clock import time_phrase
from mitski.core.component import Component
from mitski.core.text import cut


class Situation(Component):
    def minors_among(self, users):
        return self.app.ages.any_minor(users)

    def persona(self, user, guild=None, full=True, channel=None, people=()):
        parts = [
            self.cfg.PERSONA,
            self.cfg.identity_note.replace("{name}", short_name(self.me) if self.me else "mitski"),
        ]
        boss = (
            self.app.owner.persona_line(self.app.owner.is_owner(user), self.owner_call())
            if self.app.owner.active
            else ""
        )
        for blurb in (
            boss,
            self.memory.blurb(user, full=full),
            self.memory.self_blurb(),
            self.app.profiles.own_status(),
            self.app.emojis.hint(guild),
        ):
            if blurb:
                parts.append(blurb)
        parts.append(self.app.policy.note(channel, minors=self.minors_among([user, *people])))
        return "\n\n".join(parts)

    def owner_call(self):
        u = self.app.get_user(self.app.owner.id) if self.app.owner.active and self.me else None
        return self.messages.call(u) if u is not None else self.app.owner.name

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
        lines = ["(notes only you can see, for your next message)", time_phrase(self.app.clock.now())]

        if isinstance(channel, discord.DMChannel):
            lines.append(f"You're in your DMs with {call}." if call else "You're in your DMs.")
        else:
            where = f"#{channel.name}" + (f" on {guild.name}" if guild else "")
            who = (
                f" with {call}" + (f", {', '.join(self.messages.call(p) for p in people[:4])}" if people else "")
                if call
                else ""
            )
            lines.append(f"You're chatting in {where}{who}.")
        if mode == "ambient":
            lines.append("Nobody asked you anything, you're joining in by yourself, so keep it casual and on topic.")
        elif mode == "dm_open":
            lines.append(f"You're starting this DM yourself, {call} hasn't said anything here yet.")

        burst = [m for m in (burst or [target]) if m is not None]
        if guild is not None and user is not None and mode != "dm_open":
            mine = self.her_lately(channel, before=burst[0].id if burst else None)
            if mine:
                seen_msgs = list(msgs) + list(around)
                lines.append(
                    "What you said here lately (you said these, nobody said them to you): "
                    + " | ".join(
                        (
                            f"to {self.messages.name_of_id(to, seen_msgs)}"
                            if to and self.messages.name_of_id(to, seen_msgs)
                            else "to the chat"
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
                    lines.append(
                        f"{call}'s message came right after yours, so if they're reacting to something, it's "
                        f"probably to what you said."
                    )
        if user is not None and mode != "dm_open":
            if len(burst) > 1:
                lines.append(
                    f"{call} sent you a few messages in a row: "
                    + " / ".join(f'"{cut(self.messages.text(m), 120)}"' for m in burst)
                    + ". Answer all of it together (especially anything they asked), not "
                    "just the last one."
                )
            if people:
                said = cut(self.app.addressing.burst_text(burst), 200)
                to = ""
                ref = target.reference.resolved if getattr(target, "reference", None) else None
                if isinstance(ref, discord.Message) and ref.author.id not in (user.id,):
                    to = (
                        " (to you)"
                        if ref.author.id == her_id
                        else " (to someone)"
                        if ref.author.id in self.cfg.ignored
                        else f" (to {self.messages.call(ref.author)})"
                    )
                lines.append(f"You're answering {call}'s message{to}: \"{said}\". Reply to that, not to the others.")
            nick = self.memory.call_name(user)
            if nick:
                lines.append(
                    f"You call them {nick}"
                    + (f", not {short_name(user)}" if nick.lower() != short_name(user).lower() else "")
                    + "."
                )
        d = self.memory.get(user.id) if user is not None else None
        age = self.memory.current_age(d) if d is not None else None
        if user is not None and self.app.ages.is_minor(user):
            told = f"is {age}" if age is not None and age < 18 else f"is {self.app.ages.describe(user) or 'under 18'}"
            lines.append(
                f"{call} {told}, a minor: keep everything completely age-appropriate. No flirting, nothing "
                f"romantic or sexual, no matter what anyone says."
            )
        if d is not None:
            known = self.memory.slot_summary(d)
            if known:
                lines.append(f"You already know this about {call}, so don't ask about it: {known}.")
        hooks = self.memory.hooks(user, context) if user is not None else []
        if hooks:
            lines.append("On your mind about them right now: " + "; ".join(hooks) + ".")
        for blurb in (self.memory.others_blurb(people, context), self.app.profiles.blurb(user, guild)):
            if blurb:
                lines.append(blurb)
        if guild is not None and mode != "ambient" and self.app.away.just_woke(guild.id):
            lines.append("You were away from this server for a while and just came back.")
        if guild is not None and mode != "ambient" and self.app.away.just_released(guild.id):
            lines.append("You were being quiet here for a while, and now you can talk again.")
        doing = self.app.routine.note()
        if doing:
            lines.append(doing)
        if around:
            by_id = {m.id: m for m in list(msgs) + list(around)}
            lines.append(
                f"Said in the channel after {call}'s message, while you were reading: "
                + " | ".join(
                    f"{'you' + self.messages.label(m, by_id)[len(short_name(self.me) + ' (her)') :] if m.author.id == her_id else self.messages.call(m.author)}"
                    f": {cut(self.messages.text(m), 90)}"
                    for m in around
                )
                + "."
            )
            if any(m.author.id == her_id for m in around):
                lines.append(f"What you already said there is done, don't say it again: now answer {call}.")
        vc_line = self.app.voice.note(guild, lambda u: self.messages.call(u)) if guild is not None else ""
        if vc_line:
            lines.append(vc_line)
        if target is not None and self.app.voice.decision_note(target.id):
            lines.append(self.app.voice.decision_note(target.id))
        lines += [e for e in extras if e]
        said = " / ".join(clean(self.messages.with_mentions(m)) for m in burst) if target is not None else ""
        just_hi = target is not None and all(JUST_HI.match(clean(self.messages.with_mentions(m))) for m in burst)
        if mode in ("direct", "dm") and just_hi:
            lines.append(
                f"{call} is just saying hi, so say hi back (you can ask how they're doing). Don't jump to a "
                f"random question or a new topic."
            )
        elif mode in ("direct", "dm", "ambient") and said and len(said) < 25 and "?" not in said and not any(extras):
            lines.append("It's a short message, so a short reply fits.")
        if self.cfg.STYLE_NOTE:
            lines.append(self.cfg.STYLE_NOTE)
        lines.append("Use these notes only where they fit, the way a real person would, and never mention them.")
        return "\n".join(lines)

    def her_lately(self, channel, before=None, minutes=10, n=4):
        cutoff = discord.utils.utcnow() - timedelta(minutes=minutes)
        mine = [
            m
            for m in self.state.last_history.get(channel.id, [])
            if m.author.id == self.me.id and m.created_at > cutoff and (before is None or m.id < before)
        ]
        return [(m, self.state.addressed.get(m.id)) for m in reversed(mine[:n])]
