from dataclasses import dataclass, field
from datetime import timedelta

import discord

from mitski.chat.messages import short_name
from mitski.core.component import Component


@dataclass
class Context:
    turns: list | None
    msgs: list
    target: object
    others: list = field(default_factory=list)
    around: list = field(default_factory=list)

    @property
    def everything(self):
        return list(self.msgs) + list(self.around)


class ContextBuilder(Component):
    async def chat_with(self, user, channel):
        if isinstance(channel, discord.DMChannel):
            msgs = [m async for m in channel.history(limit=60)]
            return list(reversed([m for m in msgs if self.messages.usable(m)]))
        history = [m for m in [m async for m in channel.history(limit=150)] if self.messages.usable(m)]
        theirs = {m.id for m in history if m.author.id == user.id}
        replied_to = {m.reference.message_id for m in history if m.author.id == user.id and m.reference}
        picked = [
            m
            for m in history
            if m.id in theirs
            or m.id in replied_to
            or self.part_of_convo(m, user.id)
            or (m.reference is not None and m.reference.message_id in theirs)
        ]
        return sorted(picked, key=lambda m: m.id)[-60:]

    async def history(self, channel, limit=400):
        return [m async for m in channel.history(limit=limit) if self.messages.usable(m)]

    def within_gap(self, msgs):
        kept = []
        for m in msgs:
            if kept and kept[-1].created_at - m.created_at > self.cfg.context_gap:
                break
            kept.append(m)
        return kept

    def to_turns(self, msgs, keep_opener=False, need_user_last=True, names=False):
        turns = []
        by_id = {m.id: m for m in msgs}
        for i, m in enumerate(msgs):
            role = "assistant" if m.author.id == self.me.id else "user"
            text = self.messages.text(m)
            if role == "user" and names:
                note = ""
                ref = m.reference.message_id if m.reference else None
                if ref and (i == 0 or msgs[i - 1].id != ref):
                    parent = by_id.get(ref) or (
                        m.reference.resolved if isinstance(m.reference.resolved, discord.Message) else None
                    )
                    if parent is not None and parent.author.id != m.author.id:
                        note = (
                            " (replying to you)"
                            if parent.author.id == self.me.id
                            else " (replying to someone)"
                            if parent.author.id in self.cfg.ignored
                            else f" (replying to {self.messages.call(parent.author)})"
                        )
                text = f"{self.messages.call(m.author)}{note}: {text}"
            if turns and turns[-1][0] == role:
                turns[-1][1] += "\n" + text
            else:
                turns.append([role, text])
        if turns and turns[0][0] == "assistant":
            if keep_opener:
                turns.insert(0, ["user", ""])
            else:
                while turns and turns[0][0] == "assistant":
                    turns.pop(0)
        if not turns:
            return None
        if need_user_last and turns[-1][0] != "user":
            return None
        return turns

    def part_of_convo(self, m, user_id):
        if m.author.id == user_id:
            return True
        if m.author.id != self.me.id:
            return False
        if m.id in self.state.addressed:
            return self.state.addressed[m.id] == user_id
        ref = m.reference.resolved if m.reference else None
        return isinstance(ref, discord.Message) and ref.author.id == user_id

    async def reply_chain(self, msg):
        chain = []
        current = msg
        for _ in range(self.cfg.CHAIN_DEPTH):
            ref = current.reference
            if not ref or not ref.message_id:
                break
            parent = ref.resolved if isinstance(ref.resolved, discord.Message) else None
            if parent is None:
                try:
                    parent = await current.channel.fetch_message(ref.message_id)
                except discord.HTTPException:
                    break
            chain.append(parent)
            current = parent
        return chain

    async def thread_with(self, channel, trigger, user_id=None):
        user_id = user_id or trigger.author.id
        history = [m async for m in channel.history(limit=100)]
        history = [m for m in history if self.messages.usable(m)]
        self.state.last_history[channel.id] = history
        chain = [m for m in await self.reply_chain(trigger) if self.messages.usable(m)] if trigger else []
        ids = {m.id for m in chain}
        if trigger:
            ids.add(trigger.id)
        selected = []
        for m in sorted(history, key=lambda m: m.id):
            ref_id = m.reference.message_id if m.reference else None
            if m.id in ids or self.part_of_convo(m, user_id) or (ref_id is not None and ref_id in ids):
                selected.append(m)
                ids.add(m.id)
        selected = self.within_gap(list(reversed(selected)))[: self.cfg.CONTEXT_MSGS]
        have = {m.id for m in selected}
        selected += [m for m in chain if m.id not in have]
        return sorted(selected, key=lambda m: m.id, reverse=True)[: self.cfg.CONTEXT_MSGS]

    async def build(self, channel, mode, trigger):
        target = trigger
        around = []
        if mode == "dm":
            msgs = [m async for m in channel.history(limit=self.cfg.CONTEXT_MSGS)]
            msgs = list(reversed(self.within_gap([m for m in msgs if self.messages.usable(m)])))
            names = False
        elif mode == "ambient":
            window = [m async for m in channel.history(limit=self.cfg.AMBIENT_MSGS)]
            window = list(reversed(self.within_gap([m for m in window if self.messages.usable(m)])))
            target = self.app.ambient.pick_target(window) or trigger
            msgs = [m for m in window if m.id <= target.id]
            around = (
                [m for m in window if m.id > target.id][-self.cfg.MEANWHILE_MSGS :]
                if self.cfg.MEANWHILE_MSGS > 0
                else []
            )
            names = self.cfg.GROUP_NAMES
        else:
            thread = list(reversed(await self.thread_with(channel, trigger)))
            msgs = [m for m in thread if m.id <= trigger.id]
            later = [m for m in thread if m.id > trigger.id]
            cutoff = discord.utils.utcnow() - timedelta(minutes=10)
            recent = [m for m in self.state.last_history.get(channel.id, [])[:60] if m.created_at > cutoff]
            if self.cfg.CHANNEL_CONTEXT_MSGS > 0 and not isinstance(channel, discord.DMChannel):
                have = {m.id for m in msgs}
                add = [m for m in recent if m.id < trigger.id and m.id not in have][: self.cfg.CHANNEL_CONTEXT_MSGS]
                if add:
                    msgs = sorted(msgs + add, key=lambda m: m.id)[-self.cfg.CONTEXT_MSGS :]
            authors = {m.author.id for m in msgs if m.author.id != self.me.id}
            names = self.cfg.GROUP_NAMES and len(authors) > 1
            if self.cfg.MEANWHILE_MSGS > 0:
                have = {m.id for m in msgs}
                since = {m.id: m for m in later + [m for m in recent if m.id > trigger.id]}
                around = sorted(
                    (m for m in since.values() if m.id not in have),
                    key=lambda m: m.id,
                )[-self.cfg.MEANWHILE_MSGS :]
        await self.app.youtube.prefetch(msgs)
        await self.app.vision.prefetch(list(msgs) + around, skip_author=self.me.id)
        others = sorted(
            {
                n
                for m in list(msgs) + around
                if m.author.id != self.me.id
                for n in (short_name(m.author), self.messages.call(m.author))
            }
            | self.messages.speaker_names()
        )
        turns = self.to_turns(msgs, keep_opener=(mode == "dm"), names=names)
        return Context(turns, msgs, target, others, around)
