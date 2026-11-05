import asyncio
from collections import deque

from mitski.chat.messages import short_name
from mitski.core.collections import BoundedDict
from mitski.memory.commands import CommandsMixin
from mitski.memory.database import PeopleDB
from mitski.memory.embeddings import Embedder
from mitski.memory.notes import NotesMixin
from mitski.memory.recall import RecallMixin
from mitski.memory.store import PeopleStore


class Memory(NotesMixin, RecallMixin, CommandsMixin, PeopleStore):
    def __init__(self, app):
        self.app = app
        cfg = app.cfg
        self.enabled = cfg.MEMORY
        self.notes = cfg.MEMORY_NOTES
        self.notes_every = cfg.NOTES_EVERY
        self.min_gap = cfg.NOTES_MIN_GAP
        self.idle = cfg.NOTES_IDLE_MIN * 60
        self.max_per_hour = cfg.NOTES_MAX_PER_HOUR
        self.overhear = cfg.NOTES_OVERHEAR
        self.overhear_every = cfg.NOTES_OVERHEAR_EVERY
        self.facts_max = cfg.FACTS_MAX
        self.facts_in_prompt = cfg.FACTS_IN_PROMPT
        self.self_notes = cfg.SELF_NOTES
        self.self_max = cfg.SELF_MAX
        self.episodes_max = cfg.EPISODES_MAX
        self.reflect_every = cfg.REFLECT_EVERY
        self.db = PeopleDB(
            cfg.paths.data_file("memory.db"),
            legacy_people=cfg.paths.data_file("memory.json"),
            legacy_self=cfg.paths.data_file("self.json"),
        )
        self.save_lock = asyncio.Lock()
        self.embed = Embedder(cfg, lambda: app.http)
        self.people = {}
        self.own = {"facts": [], "next_id": 1}
        self.dirty = False
        self.running = set()
        self.flushes = {}
        self.last_channel = BoundedDict(2000)
        self.last_user = BoundedDict(2000)
        self.last_raw = BoundedDict(200)
        self.update_times = deque()
        self.recalled = BoundedDict(200)
        self.reflecting = set()

    @property
    def think_on(self):
        return self.app.helper.think_on

    @property
    def notes_url(self):
        return self.app.helper.url

    def her_id(self):
        return self.app.user.id if self.app.user else None

    def her_name(self):
        return short_name(self.app.user)

    @staticmethod
    def name_of(user):
        return short_name(user)

    def text_of(self, message):
        return self.app.messages.text(message)

    async def chat_of(self, user, channel):
        return await self.app.context.chat_with(user, channel)

    async def log(self, text):
        await self.app.relay.post(text)
