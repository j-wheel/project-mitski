import asyncio
import random
import sqlite3

import aiohttp
import discord

from mitski.admin.commands import AdminCommands
from mitski.admin.relay import RelayLog
from mitski.brain.planner import Brain
from mitski.brain.search import WebSearch
from mitski.brain.tools import Toolbox
from mitski.chat.addressing import Addressing
from mitski.chat.ambient import Ambient
from mitski.chat.context import ContextBuilder
from mitski.chat.drafts import DraftFilter
from mitski.chat.messages import MessageView, short_name
from mitski.chat.pipeline import ReplyPipeline
from mitski.chat.policy import ContentPolicy
from mitski.chat.review import DraftReview
from mitski.chat.router import MessageRouter
from mitski.chat.sender import Sender
from mitski.chat.situation import Situation
from mitski.chat.state import ChatState
from mitski.chat.style import Style
from mitski.core import logs
from mitski.core.clock import Clock
from mitski.core.metrics import Metrics
from mitski.core.tasks import Background
from mitski.llm.client import LlamaClient
from mitski.llm.gpu import GpuLock
from mitski.llm.helper import HelperModel
from mitski.media.emojis import Emojis
from mitski.media.extras import Extras
from mitski.media.reactions import Reactions
from mitski.media.youtube import YouTube
from mitski.memory.activity import Tracker
from mitski.memory.memory import Memory
from mitski.reminders.scheduler import ReminderScheduler
from mitski.reminders.store import Reminders
from mitski.report import startup_report
from mitski.social.ages import AgeGuard
from mitski.social.away import Away
from mitski.social.dms import DirectMessages
from mitski.social.owner import Owner, OwnerRequests
from mitski.social.presence import Profiles
from mitski.social.privacy import PrivacyCommands
from mitski.social.routine import Routine
from mitski.social.sleep import SleepCycle
from mitski.vision.service import Vision
from mitski.voice.service import Voice

log = logs.get("app")

SAVE_EVERY = 30
SWEEP_EVERY = 600
HTTP_TIMEOUT = aiohttp.ClientTimeout(total=120)


def make_client(profiles):
    intents_type = getattr(discord, "Intents", None)
    if intents_type is None:
        return discord.Client()
    intents = intents_type.default()
    intents.message_content = True
    if profiles:
        intents.presences = True
        intents.members = True
    return discord.Client(intents=intents)


class App:
    def __init__(self, cfg, client=None):
        self.cfg = cfg
        self.client = client or make_client(cfg.PROFILES)
        self.http = None
        self.started = False

        self.clock = Clock(cfg.TIMEZONE)
        self.metrics = Metrics(cfg.METRICS_WINDOW)
        self.tasks = Background()
        self.gpu = GpuLock(quiet=cfg.BACKGROUND_QUIET_SEC)
        self.state = ChatState(cfg)
        self.tracker = Tracker()
        self.style = Style(cfg)

        self.owner = Owner(cfg)
        self.away = Away(cfg, exclude=cfg.sleep_exclude)
        self.reminders = Reminders(cfg)

        self.llm = LlamaClient(self)
        self.helper = HelperModel(self)
        self.memory = Memory(self)

        self.messages = MessageView(self)
        self.context = ContextBuilder(self)
        self.addressing = Addressing(self)
        self.ambient = Ambient(self)
        self.ages = AgeGuard(self)
        self.policy = ContentPolicy(self)
        self.situation = Situation(self)
        self.drafts = DraftFilter(self)
        self.review = DraftReview(self)
        self.sender = Sender(self)
        self.pipeline = ReplyPipeline(self)
        self.router = MessageRouter(self)

        self.brain = Brain(self)
        self.search = WebSearch(self)
        self.tools = Toolbox(self)

        self.emojis = Emojis(self)
        self.reactions = Reactions(self)
        self.extras = Extras(self)
        self.youtube = YouTube(self)
        self.vision = Vision(self)
        self.voice = Voice(self)

        self.profiles = Profiles(self)
        self.dms = DirectMessages(self)
        self.requests = OwnerRequests(self)
        self.scheduler = ReminderScheduler(self)
        self.sleep = SleepCycle(self)
        self.routine = Routine(self)

        self.relay = RelayLog(self)
        self.admin = AdminCommands(self)
        self.privacy = PrivacyCommands(self)

        self._bind_events()

    @property
    def user(self):
        return self.client.user

    @property
    def guilds(self):
        return self.client.guilds

    def get_channel(self, channel_id):
        return self.client.get_channel(channel_id)

    def get_user(self, user_id):
        return self.client.get_user(user_id)

    def get_guild(self, guild_id):
        return self.client.get_guild(guild_id)

    async def fetch_user(self, user_id):
        return await self.client.fetch_user(user_id)

    async def fetch_channel(self, channel_id):
        return await self.client.fetch_channel(channel_id)

    async def change_presence(self, **kwargs):
        await self.client.change_presence(**kwargs)

    def her_guilds(self):
        return [g for g in self.guilds if any(self.messages.allowed_channel(c) for c in g.channels)]

    def _bind_events(self):
        client = self.client

        @client.event
        async def on_ready():
            await self.ready()

        @client.event
        async def on_message(msg):
            await self.router.route(msg)

        @client.event
        async def on_typing(channel, user, when):
            self.router.typing(channel, user)

        @client.event
        async def on_voice_state_update(member, before, after):
            self.voice.state_update(member, before, after)

        @client.event
        async def on_presence_update(before, after):
            if after.id not in self.cfg.ignored:
                self.profiles.track(before, after)

        @client.event
        async def on_raw_reaction_add(payload):
            self.router.reaction(payload)

    async def ready(self):
        if self.user.id in self.cfg.ignored:
            self.cfg.ignored.discard(self.user.id)
            log.warning(
                "IGNORE_USERS has her own id (%s) in it, leaving it out. remove it from the config", self.user.id
            )
        if not self.started:
            self.started = True
            await self._start()
        if not self.cfg.PROFILES:
            for guild in self.guilds:
                self.state.known_names[guild.id].update(
                    n.lower() for m in guild.members for n in (short_name(m), m.name)
                )
        await self.profiles.apply()
        for line in startup_report(self):
            log.info("%s", line)
        status, body = await self.llm.health()
        if status is None:
            log.error("llama-server isn't reachable at %s, start it first", self.cfg.llm_url)
        else:
            log.info("llama-server: %s %s", status, body.strip())

    async def _start(self):
        self.http = aiohttp.ClientSession(timeout=HTTP_TIMEOUT)
        self._load()
        await self.llm.probe()
        await self.vision.check()
        self.voice.check()
        for name, loop in (
            ("saver", self._save_loop()),
            ("janitor", self._sweep_loop()),
            ("voice", self.voice.run()),
            ("sleep", self.sleep.run()),
            ("routine", self.routine.run()),
            ("reminders", self.scheduler.run()),
        ):
            self.tasks.spawn(loop, name=name)
        self.tasks.spawn(self.vision.index_stickers(self._sticker_guilds()), name="sticker-index")

    def _load(self):
        self.memory.load()
        self.ages.load()
        self.owner.load()
        self.away.load(self.owner.data.get("quiet_until", 0))
        self.reminders.load()
        self.emojis.load()
        self.vision.load()
        for uid in self.cfg.ignored:
            if self.memory.people.pop(str(uid), None) is not None:
                log.info("forgot ignored user %s", uid)

    def _sticker_guilds(self):
        guilds = self.her_guilds()
        if self.emojis.has_nitro():
            guilds += [g for g in self.guilds if g not in guilds and g.stickers]
        return guilds

    async def save(self):
        await self.memory.flush()
        self.vision.save_if_dirty()
        if self.emojis.dirty:
            self.emojis.save()

    async def _save_loop(self):
        while True:
            await asyncio.sleep(SAVE_EVERY)
            try:
                await self.save()
            except (OSError, sqlite3.Error):
                log.warning("saving failed", exc_info=True)

    async def _sweep_loop(self):
        while True:
            await asyncio.sleep(SWEEP_EVERY * random.uniform(0.9, 1.1))
            removed = self.state.sweep() + self.tracker.sweep()
            self.memory.expire(self.cfg.MEMORY_RETENTION_DAYS)
            if removed:
                log.debug("swept %d stale entries", removed)

    async def shutdown(self):
        await self.tasks.cancel_all()
        try:
            await self.save()
        except (OSError, sqlite3.Error):
            log.warning("saving on shutdown failed", exc_info=True)
        self.memory.db.close()
        if self.http is not None:
            await self.http.close()

    async def run(self):
        async with self.client:
            try:
                await self.client.start(self.cfg.TOKEN, reconnect=True)
            finally:
                await self.shutdown()
