import asyncio
from contextlib import contextmanager

from mitski.app import App
from mitski.config import Settings
from mitski.core.metrics import Metrics
from mitski.testing.fakes import FakeChannel, FakeClient, FakeGuild, FakeMessage, FakeUser, settle

QUIET_WORLD = {
    "READ_DELAY": [0, 0],
    "READ_CPS": 10_000,
    "TYPING_CPS": 10_000,
    "DEBOUNCE_SEC": 0,
    "DISTRACTED_CHANCE": 0,
    "THINKING": False,
    "SEARCH_PROVIDER": "",
    "VISION": False,
    "VOICE": False,
    "YOUTUBE": False,
    "REACTIONS": False,
    "MEMORY": False,
    "DM_ENABLED": False,
    "PROFILES": False,
    "SLEEP_MODE": False,
    "ROUTINE": False,
    "STICKER_CHANCE": 0,
    "GIF_CHANCE": 0,
    "SPLIT_CHANCE": 0,
    "STRETCH_CHANCE": 0,
    "FLAIR_CHANCE": 0,
    "SLANG": 0,
    "NO_APOSTROPHES": 0,
    "PING_CHANCE": 0,
    "REPLY_BACK_CHANCE": 1.0,
    "ACTIVE_MIN": 1000,
    "ACTIVE_MAX": 1000,
    "BACKGROUND_QUIET_SEC": 0,
}


@contextmanager
def instant_sleep():
    real = asyncio.sleep

    async def instant(_delay=0, result=None):
        return await real(0, result)

    asyncio.sleep = instant
    try:
        yield
    finally:
        asyncio.sleep = real


class World:
    def __init__(self, app, client, guild, channel, owner, people):
        self.app, self.client, self.guild, self.channel = app, client, guild, channel
        self.owner = owner
        self.people = people
        self.replies = []
        self.prompts = []

    @property
    def her(self):
        return self.client.user

    def person(self, name):
        if name == "owner":
            return self.owner
        if name not in self.people:
            self.people[name] = FakeUser(name)
            self.guild.members.append(self.people[name])
        return self.people[name]

    def say(self, author, text, to_her=True, reference=None):
        mentions = [self.her] if to_her else []
        return FakeMessage(self.channel, author, text, mentions=mentions, reference=reference)

    async def send(self, author, text, to_her=True, reference=None):
        msg = self.say(author, text, to_her, reference)
        await self.app.router.route(msg)
        await settle(self.app)
        return msg

    def sent_text(self):
        return [m.content for m in self.client.sent]

    def script(self):
        async def generate(prompt, *args, raw=False, **kwargs):
            Metrics.llm_call("reply", 0.0)
            self.prompts.append(prompt)
            text = self.replies.pop(0) if self.replies else "ok"
            return {"content": text, "tokens_predicted": len(text.split()), "stop_type": "eos"} if raw else text

        async def no_helper(*args, **kwargs):
            return None

        self.app.llm.generate = generate
        self.app.helper.ask_json = no_helper
        return self


def build_world(paths, overrides=None, people=("anna", "bob")):
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    if not paths.config.exists():
        paths.config.write_text("CHANNELS: []\n", encoding="utf-8")
    client = FakeClient()
    guild = FakeGuild("the server")
    client.guilds.append(guild)
    channel = FakeChannel(client, guild)
    owner = FakeUser("wheeler")
    folks = {name: FakeUser(name) for name in people}
    guild.members = [client.user, owner, *folks.values()]
    values = {**QUIET_WORLD, "CHANNELS": [channel.id], "OWNER_ID": owner.id, **(overrides or {})}
    app = App(Settings.from_dict(values, paths), client=client)
    return World(app, client, guild, channel, owner, folks)
