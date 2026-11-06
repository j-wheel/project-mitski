import random
import time

import discord

from mitski.chat.messages import NORMAL_TYPES, short_name
from mitski.core import logs
from mitski.core.component import Component
from mitski.social.away import UNQUIET

log = logs.get("router")


class MessageRouter(Component):
    async def route(self, msg):
        if msg.guild is not None and self.messages.allowed_channel(msg.channel):
            self.state.chan_log[msg.channel.id].append((msg.id, msg.author.id))
        if not self._from_a_person(msg):
            return
        if await self.app.admin.dispatch(msg):
            return
        if self.cfg.LOG_CHANNEL and msg.channel.id == self.cfg.LOG_CHANNEL:
            return
        is_dm = isinstance(msg.channel, discord.DMChannel)
        if self.app.owner.is_owner(msg.author):
            self.app.owner.seen(short_name(msg.author))
        if is_dm:
            self.state.dm_unanswered.discard(msg.author.id)
            self._reply(msg, "dm")
            return
        self.app.emojis.index_message(msg)
        if self.messages.allowed_channel(msg.channel):
            await self._channel_message(msg)

    def _from_a_person(self, msg):
        author = msg.author
        if author.bot or msg.type not in NORMAL_TYPES or author.id in self.cfg.ignored:
            return False
        return self.me is not None and author.id != self.me.id

    def _reply(self, msg, mode):
        self.memory.touch(msg.author, msg.content)
        self.app.feelings.heard(msg, aimed=mode == "dm" or self.app.addressing.aimed_at_her(msg))
        self.app.ages.look_up(msg.author)
        self.app.pipeline.queue(msg.channel, mode, msg)

    async def _channel_message(self, msg):
        cid, author = msg.channel.id, msg.author
        self.app.ages.check_member(author)
        self.state.activity[cid].append(time.monotonic())
        self.state.known_names[msg.guild.id].update({short_name(author).lower(), author.name.lower()})
        if not await self._past_away_gate(msg):
            return
        if cid not in self.state.threshold_base:
            self.app.ambient.new_threshold(cid)
        addressing = self.app.addressing
        to_her = addressing.talks_to_her(msg)
        self.app.voice.heard(msg, to_her=to_her or addressing.is_engaged(cid, author.id))
        if to_her:
            addressing.engage(cid, author.id, refill=True)
            self._reply(msg, "direct")
            return
        key = (cid, author.id)
        waiting = key in self.state.waiting
        if (waiting and not addressing.for_someone_else(msg)) or (not waiting and addressing.is_follow_up(msg)):
            self._reply(msg, "direct")
            return
        self._overheard(msg, key)

    async def _past_away_gate(self, msg):
        guild, away = msg.guild, self.app.away
        state = away.state(guild.id)
        if not state:
            return True
        if not (self.app.owner.is_owner(msg.author) and self.app.addressing.talks_to_her(msg)):
            return False
        if state == "asleep":
            await self.app.sleep.wake_for(guild, msg.author)
            return True
        if UNQUIET.search(msg.content or ""):
            away.unquiet(guild.id)
            log.info("%s said she can talk again in %s", msg.author, guild.name)
            await self.app.relay.post(f"**not quiet anymore** in {guild.name}")
            return True
        self.app.pipeline.queue(msg.channel, "direct", msg)
        return False

    def _overheard(self, msg, key):
        cid = msg.channel.id
        self.state.last_msg_time[key] = time.monotonic()
        self.state.msg_count[cid] += 3 if self.app.owner.is_owner(msg.author) else 1
        self.memory.overheard(msg.author, msg.content, msg.channel)
        if self.app.ambient.should_join(cid):
            self.app.pipeline.join_in(msg.channel, msg)
        elif (
            self.cfg.REACTIONS
            and self.app.routine.free_in(getattr(msg.guild, "id", None))
            and random.random() < self.cfg.AMBIENT_REACT_CHANCE
        ):
            self.app.tasks.spawn(self.app.reactions.ambient(msg), name=f"ambient-react-{msg.id}")

    def typing(self, channel, user):
        if user.id not in self.cfg.ignored:
            self.state.last_typing[(channel.id, user.id)] = time.monotonic()

    def reaction(self, payload):
        if payload.guild_id is None or not payload.emoji.is_custom_emoji():
            return
        if (self.me and payload.user_id == self.me.id) or payload.user_id in self.cfg.ignored:
            return
        guild = self.app.get_guild(payload.guild_id)
        if guild and any(e.id == payload.emoji.id for e in guild.emojis):
            self.app.emojis.bump(payload.guild_id, "emoji", payload.emoji.name)
