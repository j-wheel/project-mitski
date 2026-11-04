import asyncio
import random
import time

from mitski.chat.messages import short_name
from mitski.core import logs
from mitski.core.clock import time_phrase
from mitski.core.component import Component

log = logs.get("sleep")

BYE_WINDOW = 15 * 60


class SleepCycle(Component):
    def state_of(self, where):
        return self.app.away.state(self.messages.guild_id(where))

    def busy_in(self, guild):
        now = time.monotonic()
        ids = {c.id for c in guild.channels}
        if any(k[0] in ids and e.live(now) for k, e in self.state.engaged.items()):
            return True
        return any(self.state.channel_busy(c) for c in ids)

    async def say_bye(self, guild):
        last = self.state.her_spoke.get(guild.id)
        if not last or time.time() - last[1] > BYE_WINDOW or random.random() >= self.app.away.bye_chance:
            return
        channel = last[0]
        trigger = None
        async for m in channel.history(limit=1):
            trigger = m
        if trigger is None:
            return
        context = await self.app.context.build(channel, "ambient", trigger)
        if not context.turns:
            return
        note = (
            "(notes only you can see, for your next message)\n"
            f"{time_phrase(self.app.clock.now())}\n"
            "You're heading off for a while now (sleep, food, irl stuff, whatever fits the time). Say a quick bye to "
            "the chat, one short line, no big explanation."
        )
        persona = self.cfg.PERSONA + "\n\n" + self.cfg.identity_note.replace("{name}", short_name(self.me))
        text = await self.llm.generate(self.llm.prompt(context.turns, persona, note))
        lines = self.app.drafts.tidy(text, channel.id, context.others)[:2]
        if lines:
            sent = await self.app.sender.send(channel, lines)
            self.app.sender.remember(sent, None)
            log.info("said bye in #%s: %s", channel.name, " | ".join(lines))

    async def go_away(self, guild, hours=None, why="felt like it", bye=True):
        hours = hours or self.app.away.nap_hours(self.app.clock.late)
        if bye:
            try:
                await self.say_bye(guild)
            except Exception:
                log.warning("saying bye in %s failed", guild.name, exc_info=True)
        self.app.away.sleep(guild.id, hours, why)
        self.state.forget_guild({c.id for c in guild.channels})
        if self.app.voice.where(guild) is not None:
            self.app.tasks.spawn(self.app.voice.leave("went away"), name="voice-leave")
        log.info("gone from %s for %.1fh (%s)", guild.name, hours, why)
        await self.app.relay.post(f"**went away** from {guild.name} for {hours:.1f}h ({why})")

    async def wake_for(self, guild, by):
        self.app.away.wake(guild.id)
        log.info("%s woke her up in %s", by, guild.name)
        await self.app.relay.post(f"**back** in {guild.name} ({by.display_name} pinged her)")

    async def tick(self):
        for gid in self.app.away.ended():
            name = getattr(self.app.get_guild(gid), "name", gid)
            log.info("back in %s", name)
            await self.app.relay.post(f"**back** in {name}")
        if not self.app.routine.free:
            return
        late = self.app.clock.late
        for guild in self.app.her_guilds():
            if self.busy_in(guild) or self.app.voice.where(guild) is not None:
                continue
            if self.app.away.wants_nap(guild.id, late):
                await self.go_away(guild, why="late, went to sleep" if late else "felt like it")

    async def run(self):
        await asyncio.sleep(120)
        while True:
            try:
                await self.tick()
            except Exception:
                log.warning("sleep check failed", exc_info=True)
            await asyncio.sleep(self.app.away.tick * random.uniform(0.8, 1.2))
