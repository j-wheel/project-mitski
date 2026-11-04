import random
import re
import time
from collections import defaultdict

import discord

from mitski.chat.messages import clean
from mitski.chat.patterns import NEVER, YT_URL
from mitski.core.collections import window_count
from mitski.core.component import Component

SECOND_PERSON = re.compile(r"\b(u|you|ur|your|youre|you're|anyone|someone|who|y'?all|guys|chat)\b", re.I)


class Ambient(Component):
    def busy_factor(self, channel_id):
        now = time.monotonic()
        recent = sum(1 for t in self.state.activity[channel_id] if now - t <= 300)
        per_min = recent / 5
        return min(4.0, max(0.6, 0.6 + per_min / self.cfg.BUSY_RATE))

    def new_threshold(self, channel_id):
        self.state.msg_count[channel_id] = 0
        self.state.threshold_base[channel_id] = random.randint(self.cfg.ACTIVE_MIN, self.cfg.ACTIVE_MAX)

    def should_join(self, channel_id):
        if self.app.sleep.state_of(channel_id) or not self.app.routine.free:
            return False
        now = time.monotonic()
        factor = self.busy_factor(channel_id)
        if self.state.msg_count[channel_id] < round(self.state.threshold_base[channel_id] * factor):
            return False
        if now - self.state.last_active.get(channel_id, NEVER) < self.cfg.ACTIVE_COOLDOWN * factor:
            return False
        if window_count(self.state.ambient_times[channel_id], 3600, now) >= self.cfg.MAX_AMBIENT_PER_HOUR:
            return False
        return not self.state.channel_busy(channel_id)

    def pick_target(self, window):
        candidates = [m for m in window[-8:] if m.author.id != self.me.id]
        if not candidates:
            return None
        n = max(len(window), 1)
        pace = min(self.busy_factor(window[-1].channel.id), 2.5)
        pos = {m.id: i for i, m in enumerate(window)}
        my_last = max((i for i, m in enumerate(window) if m.author.id == self.me.id), default=-1)
        replies = defaultdict(set)
        for m in window:
            if m.reference and m.reference.message_id:
                replies[m.reference.message_id].add(m.author.id)

        def score(m):
            i = pos[m.id]
            s = 2.0 * pace * (i + 1) / n
            if "?" in m.content:
                s += 2.5
            if SECOND_PERSON.search(m.content):
                s += 1.0
            if self.app.addressing.is_engaged(m.channel.id, m.author.id):
                s += 1.5
            if len(clean(m.content)) > 25:
                s += 0.5
            if YT_URL.search(m.content):
                s += 1.0
            hint = self.app.addressing.addressee_hint(m)
            if hint == "other":
                s -= 3.0
            elif hint == "her":
                s += 2.0
            elif hint == "all":
                s += 1.0
            if m.attachments or m.stickers or any(e.type in ("gifv", "image") for e in m.embeds):
                s += 0.8
            ref = m.reference.resolved if m.reference else None
            if isinstance(ref, discord.Message) and ref.author.id not in (self.me.id, m.author.id):
                s -= 1.5
            if any(u.id != self.me.id for u in m.mentions):
                s -= 1.0
            who_replied = replies.get(m.id, set())
            if self.me.id in who_replied or any(
                x.author.id == self.me.id and self.state.addressed.get(x.id) == m.author.id for x in window[i + 1 :]
            ):
                s -= 4.0
            elif who_replied - {m.author.id}:
                s -= 2.0 if "?" in m.content else 1.0
            if i < my_last:
                s -= 2.0
            nxt = window[i + 1] if i + 1 < len(window) else None
            if (
                nxt is not None
                and nxt.author.id == m.author.id
                and (nxt.created_at - m.created_at).total_seconds() < 90
            ):
                s -= 1.2
            return s + random.uniform(0, 1)

        return max(candidates, key=score)

    def chat_active(self, guild, minutes=20):
        now = time.monotonic()
        seen = self.state.activity
        return any(seen.get(c.id) and now - seen[c.id][-1] < minutes * 60 for c in guild.channels)
