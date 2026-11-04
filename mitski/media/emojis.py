import difflib
import random
import re
import time

from mitski.chat.patterns import CUSTOM_EMOJI
from mitski.core.component import Component
from mitski.core.storage import JsonFile

try:
    import emoji as emoji_lib
except ImportError:
    emoji_lib = None

DISTINCT_NAME = re.compile(r"(?=.*[a-z])(?=.*[A-Z])|_|\d")


class EmojiFinder:
    def __init__(self, pool):
        self.pool = pool
        self.exact = {e.name: e for e in pool}
        self.lower = {e.name.lower(): e for e in pool}
        self.squash = {e.name.lower().replace("_", ""): e for e in pool}

    def custom(self, name, fuzzy=True):
        e = self.exact.get(name) or self.lower.get(name.lower()) or self.squash.get(name.lower().replace("_", ""))
        if e is None and fuzzy and len(name) >= 4 and self.lower:
            close = difflib.get_close_matches(name.lower(), list(self.lower), n=1, cutoff=0.85)
            e = self.lower[close[0]] if close else None
        return e

    @staticmethod
    def normal(name):
        if emoji_lib is None:
            return None
        for n in (name, name.lower(), name.lower().replace(" ", "_")):
            uni = emoji_lib.emojize(f":{n}:", language="alias")
            if uni != f":{n}:":
                return uni
        return None

    def resolve(self, name):
        e = self.custom(name)
        return str(e) if e is not None else self.normal(name)


class Emojis(Component):
    def __init__(self, app):
        super().__init__(app)
        self.file = JsonFile(app.cfg.paths.data_file("server_index.json"))
        self.index = {}
        self.dirty = False

    def load(self):
        self.index = self.file.load()

    def save(self):
        self.file.save(self.index)
        self.dirty = False

    def has_nitro(self):
        if self.cfg.nitro == "auto":
            pt = getattr(self.me, "premium_type", None)
            return bool(getattr(self.me, "premium", False)) or (
                pt is not None and getattr(pt, "value", pt) not in (0, None)
            )
        return bool(self.cfg.nitro)

    def finder(self, guild):
        return EmojiFinder(self.usable(guild))

    def external_ok(self, guild, kind="emojis"):
        if not self.has_nitro():
            return False
        if guild is None:
            return True
        me = getattr(guild, "me", None)
        perms = getattr(me, "guild_permissions", None)
        return True if perms is None else bool(getattr(perms, f"use_external_{kind}", True))

    def uses(self, name, guild=None):
        if guild is not None:
            return self.index.get(str(guild.id), {}).get("emoji", {}).get(name, 0)
        return sum(g.get("emoji", {}).get(name, 0) for g in self.index.values())

    def usable(self, guild):
        nitro = self.has_nitro()
        pool = [e for e in (guild.emojis if guild else []) if e.available and e.is_usable()]
        if self.external_ok(guild, "emojis"):
            here = {e.id for e in pool}
            pool += sorted(
                (e for e in self.app.client.emojis if e.available and e.is_usable() and e.id not in here),
                key=lambda e: -self.uses(e.name),
            )
        return [e for e in pool if nitro or not e.animated]

    def fix(self, line, guild):
        find = self.finder(guild)
        keep = []

        def hold(text):
            keep.append(text)
            return f"\x00{len(keep) - 1}\x00"

        def full(m):
            out = find.resolve(m.group(1))
            return hold(out) if out else ("" if self.cfg.DROP_UNKNOWN_EMOJIS else m.group(0))

        line = re.sub(r"<a?:(\w{2,32}):\d*>", lambda m: f":{m.group(1)}:", line)
        line = re.sub(r":{2,}(\w{2,32}):{2,}", r":\1:", line)
        line = re.sub(r"(?<![\w<]):(\w{2,32}):(?![\w>])", full, line)

        def half(m):
            name = m.group(1)
            e = find.custom(name, fuzzy=False)
            if e is not None and (DISTINCT_NAME.search(name) or m.end() == len(line.rstrip())):
                return hold(str(e))
            return m.group(0)

        line = re.sub(r"(?<![\w:<\x00])(\w{2,32}):(?![\w:/\x00])", half, line)
        line = re.sub(r"(?<![\w:<\x00]):(\w{2,32})(?![\w:\x00])", half, line)

        def bare(m):
            name = m.group(1)
            e = find.exact.get(name)
            return hold(str(e)) if e is not None and DISTINCT_NAME.search(name) and not name.isdigit() else name

        line = re.sub(r"(?<![\w:<@#/\x00])([A-Za-z]\w{2,31})(?![\w:>\x00])", bare, line)
        line = re.sub(r"\x00(\d+)\x00", lambda m: keep[int(m.group(1))], line)
        return re.sub(r"[ \t]+", " ", line).strip()

    def bump(self, guild_id, kind, name):
        g = self.index.setdefault(str(guild_id), {"emoji": {}, "stickers": {}})
        g.setdefault(kind, {})
        g[kind][name] = g[kind].get(name, 0) + 1
        self.dirty = True

    def index_message(self, msg):
        if msg.guild is None:
            return
        own = {e.name for e in msg.guild.emojis}
        for name in CUSTOM_EMOJI.findall(msg.content):
            if name in own:
                self.bump(msg.guild.id, "emoji", name)
        for s in msg.stickers:
            self.bump(msg.guild.id, "stickers", s.name)

    def ranked(self, guild):
        nitro = self.has_nitro()
        here = sorted(
            (e for e in (guild.emojis if guild else []) if e.available and e.is_usable() and (nitro or not e.animated)),
            key=lambda e: -self.uses(e.name, guild),
        )
        if not self.external_ok(guild, "emojis"):
            return here
        ids = {e.id for e in here}
        return here + sorted(
            (e for e in self.app.client.emojis if e.available and e.is_usable() and e.id not in ids),
            key=lambda e: -self.uses(e.name),
        )

    def stickers(self, guild):
        def uses(st, g=None):
            if g is not None:
                return self.index.get(str(g.id), {}).get("stickers", {}).get(st.name, 0)
            return sum(x.get("stickers", {}).get(st.name, 0) for x in self.index.values())

        here = sorted((st for st in (guild.stickers if guild else []) if st.available), key=lambda st: -uses(st, guild))
        if not self.external_ok(guild, "stickers"):
            return here
        ids = {st.id for st in here}
        others = [
            st for g in self.app.guilds if g is not guild for st in g.stickers if st.available and st.id not in ids
        ]
        return here + sorted(others, key=lambda st: -uses(st))

    def hint(self, guild):
        ranked = self.ranked(guild)
        if not ranked or self.cfg.EMOJI_HINT_MAX <= 0:
            return ""
        top = ranked[: max(1, self.cfg.EMOJI_HINT_MAX - 5)]
        rest = ranked[len(top) :]
        seed = (guild.id if guild else 0) + int(time.time() // 3600)
        rng = random.Random(seed)
        top += rng.sample(rest, min(5, len(rest)))
        if self.external_ok(guild, "emojis"):
            return "Custom emojis you can use (you have nitro, so emojis from any server work): " + " ".join(
                f":{e.name}:" for e in top
            )
        return "Custom emojis on this server you can use: " + " ".join(f":{e.name}:" for e in top)

    def find_sticker(self, guild, name):
        name = re.sub(r"\s*\(.*$", "", name).strip().lower()
        for s in self.stickers(guild):
            if s.name.lower() == name:
                return s
        return None
