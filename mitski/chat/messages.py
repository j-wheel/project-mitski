import re

import discord

from mitski.admin.registry import parse
from mitski.chat.patterns import (
    ANY_URL,
    CHANNEL_MENTION,
    CUSTOM_EMOJI,
    EVERYONE_MENTION,
    ROLE_MENTION,
    USER_MENTION,
    YT_URL,
)
from mitski.core.component import Component
from mitski.llm import prompt_format

NORMAL_TYPES = (discord.MessageType.default, discord.MessageType.reply)
SELF_WORDS = {"", "me", "myself", "i", "them", "us"}


def clean(text):
    text = prompt_format.scrub(text)
    text = USER_MENTION.sub("", text)
    text = ROLE_MENTION.sub("", text)
    text = CHANNEL_MENTION.sub("", text)
    text = EVERYONE_MENTION.sub("", text)
    text = CUSTOM_EMOJI.sub(r":\1:", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"[ \t]+,", ",", text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = text.strip()
    text = re.sub(r"^,\s*", "", text)
    text = re.sub(r"^:\s+", "", text)
    return text.strip()


def short_name(user):
    name = getattr(user, "display_name", None) or getattr(user, "name", "") or "someone"
    name = re.sub(r"\s*[\[\(\{].*?[\]\)\}]", "", name).strip()
    core = re.sub(r"^[\W_]+|[\W_]+$", "", name)
    return core or name or getattr(user, "name", "someone")


class MessageView(Component):
    def with_mentions(self, m):
        text = m.content or ""
        for u in getattr(m, "mentions", None) or []:
            if self.me and u.id == self.me.id:
                text = re.sub(rf"<@!?{u.id}>", "@" + short_name(self.me), text)
                continue
            if u.id in self.cfg.ignored:
                text = re.sub(rf"<@!?{u.id}>", "@someone", text)
                continue
            name = self.call(u)
            text = re.sub(rf"<@!?{u.id}>", lambda _m, n=name: "@" + n, text)
        return text

    def text(self, m):
        text = clean(self.with_mentions(m))
        tags = []
        for vid in dict.fromkeys(YT_URL.findall(m.content)):
            info = self.app.youtube.cache.get(vid)
            tags.append(f"[youtube video: {info['title']}]" if info and info.get("title") else "[youtube video]")
        tags += self.app.vision.tags(m)
        if not tags and not text and ANY_URL.search(m.content):
            tags.append("[gif]" if re.search(r"giphy\.com|tenor\.com", m.content, re.I) else "[link]")
        if not text and not tags and m.attachments:
            kind = (m.attachments[0].content_type or "").split("/")[0]
            tags.append({"audio": "[audio]", "video": "[video]"}.get(kind, "[file]"))
        return " ".join([text] + tags).strip()

    def guild_id(self, where):
        if where is None:
            return None
        if isinstance(where, int):
            ch = self.app.get_channel(where)
            return getattr(getattr(ch, "guild", None), "id", None)
        g = getattr(where, "guild", None)
        return getattr(g, "id", None)

    def allowed_channel(self, channel):
        return channel.id in self.cfg.channels or getattr(channel, "parent_id", None) in self.cfg.channels

    def call(self, user):
        return self.memory.call_name(user) or short_name(user)

    def own_names(self):
        return {short_name(self.me), self.me.name} if self.me else set()

    def member(self, user, guild):
        if user is None:
            return None
        if guild is not None:
            return guild.get_member(user.id) or (user if isinstance(user, discord.Member) else None)
        for g in self.app.guilds:
            m = g.get_member(user.id)
            if m is not None:
                return m
        return None

    def usable(self, m):
        if m.author.id in self.cfg.ignored and m.author.id != self.me.id:
            return False
        if m.type not in NORMAL_TYPES:
            return False
        if m.author.bot and m.author.id != self.me.id:
            return False
        if m.id in self.state.command_replies or parse(m.content, self.cfg.COMMAND_PREFIX) is not None:
            return False
        return bool(self.text(m))

    def speaker_names(self):
        return {n for n in self.memory.all_names() if len(n) >= 3 and not re.search(r"[^\w .'-]", n)}

    def people_in(self, msgs):
        out = {}
        for m in msgs:
            u = m.author
            if u.id == self.me.id or u.id in self.cfg.ignored or u.bot:
                continue
            for n in (short_name(u), self.call(u), u.name):
                if n and " " not in n:
                    out.setdefault(n.lower(), u)
        return out

    def label(self, m, pool_by_id):
        her = short_name(self.me)
        who = f"{her} (her)" if m.author.id == self.me.id else self.call(m.author)
        ref = m.reference
        parent = pool_by_id.get(ref.message_id) if ref and ref.message_id else None
        if parent is None and ref is not None and isinstance(ref.resolved, discord.Message):
            parent = ref.resolved
        if parent is not None and parent.author.id != m.author.id:
            who += f" (replying to {her if parent.author.id == self.me.id else self.call(parent.author)})"
        elif m.author.id == self.me.id and self.state.addressed.get(m.id):
            to = next((x.author for x in pool_by_id.values() if x.author.id == self.state.addressed[m.id]), None)
            if to is not None:
                who += f" (to {self.call(to)})"
        return who

    def name_of_id(self, uid, msgs=()):
        for m in msgs:
            if m.author.id == uid:
                return self.call(m.author)
        u = self.app.get_user(uid) if uid else None
        return self.call(u) if u is not None else None

    def guild(self, any_id):
        g = self.app.get_guild(any_id)
        if g is None:
            g = getattr(self.app.get_channel(any_id), "guild", None)
        return g

    def names_of(self, user):
        return {short_name(user).lower(), user.name.lower(), (self.call(user) or "").lower()}

    def resolve_person(self, who, guild, asker=None, context=(), fallback=True):
        w = re.sub(r"^@", "", str(who or "")).strip().lower()
        if w in SELF_WORDS:
            return asker if fallback else None
        for m in context:
            for u in getattr(m, "mentions", None) or []:
                if u.id != self.me.id and w in self.names_of(u):
                    return u
        if fallback:
            for m in context:
                for u in getattr(m, "mentions", None) or []:
                    if u.id != self.me.id:
                        return u
        for m in reversed(list(context)):
            if w in self.names_of(m.author):
                return m.author
        uid, _ = self.memory.find_person(w)
        if uid is not None:
            u = (guild.get_member(int(uid)) if guild is not None else None) or self.app.get_user(int(uid))
            if u is not None:
                return u
        for m in guild.members if guild is not None else []:
            if w in self.names_of(m) | {str(getattr(m, "global_name", "") or "").lower()}:
                return m
        return None
