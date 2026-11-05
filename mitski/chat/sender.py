import asyncio
import random
import time

import discord

from mitski.chat import convo, shape, typos
from mitski.chat.messages import short_name
from mitski.chat.patterns import NO_PINGS, PING_TAG, STICKER_TAG
from mitski.core import logs
from mitski.core.component import Component
from mitski.core.metrics import Metrics

log = logs.get("sender")

GONE_OR_INVALID = (10008, 50035, 160002)
TYPING_MAX = 8
LONG_TYPING_MAX = 20


class Sender(Component):
    def __init__(self, app):
        super().__init__(app)
        self.last_sent = {}

    def remember(self, sent, user_id):
        for m in sent:
            self.state.addressed[m.id] = user_id

    def may_ping(self, user):
        if (
            not self.cfg.PINGS
            or user is None
            or user.id in self.cfg.ignored
            or (self.me and user.id == self.me.id)
            or getattr(user, "bot", False)
        ):
            return False
        names = {
            short_name(user),
            self.messages.call(user),
            getattr(user, "name", ""),
            getattr(user, "display_name", ""),
        }
        return not convo.ping_forbidden([o["text"] for o in self.app.owner.data.get("orders", [])], names)

    def styled(self, lines, parts, serious, layout):
        if parts and layout == shape.BLOCK:
            return [self.app.style.joined(parts, serious)]
        if parts and layout == shape.THREADED:
            return [self.app.style.joined([part], serious) for part in parts]
        return self.app.style.reply(lines, serious)

    async def send(
        self,
        channel,
        lines,
        *,
        reply_to=None,
        already_typed=0.0,
        serious=False,
        ping=None,
        ping_end=False,
        people=None,
        reply_ping=None,
        plan=None,
        parts=None,
        layout=shape.QUICK,
        targets=None,
        longer=False,
    ):
        styled = self.styled(lines, parts, serious, layout)
        recent = [uid for _, uid in list(self.state.chan_log.get(channel.id, ()))[-30:]]
        audience = [*recent, *(u.id for u in (people or {}).values()), getattr(ping, "id", None)]
        if reply_to is not None:
            audience.append(reply_to.author.id)
        lines = self.app.policy.clean_lines(styled, channel, minors=self.app.ages.any_minor(audience))
        if len(lines) < len(styled):
            log.warning("held back %d explicit line(s) in %s", len(styled) - len(lines), channel)
            Metrics.event("explicit held back")
        kept_targets = []
        if targets and layout == shape.THREADED:
            for text, target in zip(styled, targets, strict=False):
                if len(kept_targets) < len(lines) and lines[len(kept_targets)] == text:
                    kept_targets.append(target)
        out = Outgoing(
            channel,
            reply_to=reply_to,
            anchor=reply_to,
            ping=ping,
            ping_end=ping_end,
            reply_ping=(self.cfg.reply_ping is True) if reply_ping is None else reply_ping,
            decided=plan is None,
        )
        if ping is not None and plan is None:
            lines = convo.add_ping(lines, ping.id, ping_end)
            out.allowed.add(ping.id)
            out.ping_done = True
        text_lines = [i for i, ln in enumerate(lines) if not STICKER_TAG.fullmatch(ln)]
        last_text = text_lines[-1] if text_lines else -1
        for i, line in enumerate(lines):
            tag = STICKER_TAG.fullmatch(line)
            if tag:
                await self._sticker(out, tag.group(1))
                continue
            out.own_target = kept_targets[i] if i < len(kept_targets) else None
            line = self.app.emojis.fix(line, out.guild)
            line, pinged = convo.real_pings(line, people or {}, self.may_ping)
            out.allowed |= {u.id for u in pinged}
            if not line:
                continue
            line, typo = self._maybe_typo(line)
            await self._type(out, line, already_typed, LONG_TYPING_MAX if longer else TYPING_MAX)
            if not out.decided and not out.apply(plan()):
                return out.sent
            line = out.with_ping(line, is_last=i == last_text)
            await self._post(out, line)
            if typo is not None:
                self._maybe_fix(out.sent[-1], typo)
        return out.sent

    def _maybe_typo(self, line):
        if random.random() >= typos.chance(line, self.cfg.TYPO_CHANCE):
            return line, None
        line, typo = typos.add_typo(line, random)
        if typo is not None:
            Metrics.event("typo")
        return line, typo

    def _maybe_fix(self, msg, typo):
        if random.random() >= self.cfg.TYPO_FIX_CHANCE:
            return
        low, high = (list(self.cfg.TYPO_FIX_DELAY) + [3, 12])[:2]
        delay = random.uniform(min(low, high), max(low, high))
        self.app.tasks.spawn(self._fix_typo(msg, typo, delay), name=f"fix-typo-{msg.id}")

    async def _fix_typo(self, msg, typo, delay):
        await asyncio.sleep(delay)
        fixed = typos.fix(msg.content, *typo)
        if fixed is None or self._away(msg.channel):
            return
        latest = self.last_sent.get(msg.channel.id) == msg.id
        try:
            if latest and random.random() < self.cfg.TYPO_STAR_CHANCE:
                await self._star(msg.channel, typo[1])
                how = "with a *"
            else:
                await msg.edit(content=fixed, allowed_mentions=NO_PINGS)
                how = "by editing"
        except discord.HTTPException as e:
            log.info("couldn't fix a typo (%s)", e.text or e.code)
            return
        Metrics.event("typo fixed")
        log.info("fixed a typo %s: %s -> %s", how, *typo)

    async def _star(self, channel, word):
        async with self.app.voice.typing_in(channel):
            await asyncio.sleep(random.uniform(0.4, 1.2))
        msg = await channel.send(typos.star(word, random), allowed_mentions=NO_PINGS)
        self.last_sent[channel.id] = msg.id
        self.state.recent_said[channel.id].append(msg.content)
        Metrics.sent()

    def _away(self, channel):
        guild = getattr(channel, "guild", None)
        return guild is not None and (self.app.away.asleep(guild.id) or self.app.away.is_quiet(guild.id))

    async def _sticker(self, out, name):
        sticker = self.app.emojis.find_sticker(out.guild, name)
        if sticker is None:
            return
        await asyncio.sleep(random.uniform(0.6, 1.8))
        try:
            out.sent.append(await out.channel.send(stickers=[sticker], allowed_mentions=NO_PINGS))
        except discord.HTTPException as e:
            log.warning("sticker failed: %s", e)

    async def _type(self, out, line, already_typed, longest=None):
        longest = TYPING_MAX if longest is None else longest
        seconds = min(len(line) / (self.cfg.TYPING_CPS * random.uniform(0.8, 1.2)), longest) + random.uniform(0.2, 0.8)
        if not out.sent:
            seconds = max(0.0, seconds - already_typed)
        else:
            await asyncio.sleep(random.uniform(0.4, 1.5))
        if seconds > 0:
            async with self.app.voice.typing_in(out.channel):
                await asyncio.sleep(seconds)

    async def _post(self, out, line):
        ids = [int(x) for x in dict.fromkeys(PING_TAG.findall(line)) if int(x) in out.allowed]
        mentions = (
            discord.AllowedMentions(
                everyone=False, roles=False, replied_user=False, users=[discord.Object(x) for x in ids]
            )
            if ids
            else NO_PINGS
        )
        target = out.reply_to if not out.sent else None
        if out.sent and out.anchor is not None and self.others_since(out.channel, out.sent[-1].id):
            target = out.anchor
        if out.own_target is not None:
            own, opens_it = out.own_target
            target = own if opens_it or self.others_since(out.channel, out.sent[-1].id) else None
        msg = None
        if target is not None:
            try:
                msg = await target.reply(
                    line, mention_author=bool(out.reply_ping) and not out.sent, allowed_mentions=mentions
                )
            except discord.HTTPException as e:
                if e.code not in GONE_OR_INVALID:
                    raise
                log.warning("couldn't reply to %s's message (%s), sending it plain", target.author, e.text or e.code)
        if msg is None:
            msg = await out.channel.send(line, allowed_mentions=mentions)
        out.sent.append(msg)
        self.last_sent[out.channel.id] = msg.id
        Metrics.sent()
        self.state.recent_said[out.channel.id].append(line)
        if out.guild is not None:
            self.state.her_spoke[out.guild.id] = (out.channel, time.time())

    def others_since(self, channel, msg_id):
        me = self.me.id
        return any(mid > msg_id and uid != me for mid, uid in self.state.chan_log.get(channel.id, ()))


class Outgoing:
    def __init__(self, channel, reply_to, anchor, ping, ping_end, reply_ping, decided):
        self.channel = channel
        self.guild = getattr(channel, "guild", None)
        self.reply_to = reply_to
        self.anchor = anchor
        self.ping = ping
        self.ping_end = ping_end
        self.reply_ping = reply_ping
        self.decided = decided
        self.ping_done = False
        self.own_target = None
        self.allowed = set()
        self.sent = []

    def apply(self, delivery):
        self.decided = True
        if delivery is None:
            return False
        self.reply_to = delivery.msg if delivery.kind == "reply" else None
        self.anchor = delivery.msg
        self.ping = delivery.user if delivery.kind == "ping" else None
        self.ping_end = delivery.at_end
        if delivery.reply_ping is not None:
            self.reply_ping = delivery.reply_ping
        return True

    def with_ping(self, line, is_last):
        if self.ping is None or self.ping_done or (self.ping_end and not is_last):
            return line
        tag = f"<@{self.ping.id}>"
        if tag not in line:
            line = f"{line} {tag}" if self.ping_end else f"{tag} {line}"
        self.allowed.add(self.ping.id)
        self.ping_done = True
        return line
