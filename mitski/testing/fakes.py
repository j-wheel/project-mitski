import asyncio
import itertools
from datetime import UTC, datetime

import discord

_ids = itertools.count(100_000_000_000_000_000)


def snowflake():
    return next(_ids)


class FakeUser:
    def __init__(self, name, uid=None, bot=False):
        self.id = uid or snowflake()
        self.name = name
        self.display_name = name
        self.global_name = name
        self.bot = bot
        self.mention = f"<@{self.id}>"
        self.dm_channel = None
        self.voice = None
        self.premium_type = None
        self.activities = ()
        self.roles = []
        self.status = discord.Status.online
        self.premium_since = None
        self.created_at = datetime(2020, 1, 1, tzinfo=UTC)
        self.joined_at = datetime(2021, 1, 1, tzinfo=UTC)

    def is_on_mobile(self):
        return False

    def __repr__(self):
        return self.name

    __str__ = __repr__


class FakeRole:
    def __init__(self, name, default=False):
        self.id = snowflake()
        self.name = name
        self.default = default
        self.managed = False

    def is_default(self):
        return self.default


class FakeProfile:
    def __init__(self, bio="", guild_bio=None):
        self.bio = bio
        self.guild_bio = guild_bio


class FakeTyping:
    def __init__(self, channel):
        self.channel = channel

    async def __aenter__(self):
        self.channel.typed += 1
        return self

    async def __aexit__(self, *exc):
        return False


class FakeGuild:
    def __init__(self, name="server"):
        self.id = snowflake()
        self.name = name
        self.channels = []
        self.voice_channels = []
        self.members = []
        self.emojis = []
        self.stickers = []
        self.me = None
        self.afk_channel = None

    def get_member(self, uid):
        return next((m for m in self.members if m.id == uid), None)


class FakeChannel:
    def __init__(self, client, guild, name="general"):
        self.id = snowflake()
        self.client = client
        self.guild = guild
        self.name = name
        self.parent_id = None
        self.nsfw = False
        self.messages = []
        self.typed = 0
        guild.channels.append(self)

    def __str__(self):
        return self.name

    def typing(self):
        return FakeTyping(self)

    def is_nsfw(self):
        return self.nsfw

    async def history(self, limit=100):
        for m in list(reversed(self.messages))[:limit]:
            yield m

    async def fetch_message(self, mid):
        for m in self.messages:
            if m.id == mid:
                return m
        raise discord.NotFound(_Response(404), "unknown message")

    async def send(self, content=None, stickers=None, allowed_mentions=None, reference=None):
        msg = FakeMessage(self, self.client.user, content or "", reference=reference)
        self.client.sent.append(msg)
        return msg


class _Response:
    def __init__(self, status):
        self.status = status
        self.reason = "fake"


class FakeReference:
    def __init__(self, message):
        self.message_id = message.id
        self.resolved = message


class FakeMessage:
    def __init__(self, channel, author, content, mentions=(), reference=None):
        self.id = snowflake()
        self.channel = channel
        self.guild = getattr(channel, "guild", None)
        self.author = author
        self.content = content
        self.clean_content = content
        self.mentions = list(mentions)
        self.channel_mentions = []
        self.role_mentions = []
        self.attachments = []
        self.stickers = []
        self.embeds = []
        self.reactions = []
        self.type = discord.MessageType.default
        self.created_at = datetime.now(UTC)
        self.reference = FakeReference(reference) if isinstance(reference, FakeMessage) else None
        self.jump_url = f"https://discord.com/channels/0/{channel.id}/{self.id}"
        channel.messages.append(self)

    async def reply(self, content, mention_author=False, allowed_mentions=None):
        msg = FakeMessage(self.channel, self.channel.client.user, content, reference=self)
        self.channel.client.sent.append(msg)
        return msg

    async def add_reaction(self, emoji):
        self.reactions.append(emoji)

    async def edit(self, content=None, allowed_mentions=None, **kwargs):
        self.edits = [*getattr(self, "edits", []), self.content]
        self.content = self.clean_content = content
        return self


class FakeDM(discord.DMChannel):
    def __init__(self, client, user):
        self.id = snowflake()
        self.recipients = [user]
        self.me = client.user
        self._state = None
        self.client = client
        self.messages = []
        self.typed = 0

    def __str__(self):
        return f"dm with {self.recipient}"

    typing = FakeChannel.typing
    history = FakeChannel.history
    fetch_message = FakeChannel.fetch_message
    send = FakeChannel.send


class FakeClient:
    def __init__(self, name="mitski"):
        self.user = FakeUser(name)
        self.guilds = []
        self.emojis = []
        self.sent = []
        self.friends = []
        self.handlers = {}
        self.presence = None

    def event(self, fn):
        self.handlers[fn.__name__] = fn
        return fn

    def get_channel(self, cid):
        return next((c for g in self.guilds for c in g.channels if c.id == cid), None)

    def get_guild(self, gid):
        return next((g for g in self.guilds if g.id == gid), None)

    def get_user(self, uid):
        return next((m for g in self.guilds for m in g.members if m.id == uid), None)

    async def fetch_user(self, uid):
        return self.get_user(uid)

    async def fetch_channel(self, cid):
        return self.get_channel(cid)

    async def change_presence(self, **kwargs):
        self.presence = kwargs

    async def close(self):
        pass


async def settle(app, timeout=10):
    for _ in range(200):
        pending = [t for t in app.tasks._tasks if not t.done()]
        if not pending:
            return
        await asyncio.wait(pending, timeout=timeout)
