import asyncio
import random
import re
import time

import discord

from mitski.chat.messages import short_name
from mitski.core import logs
from mitski.core.collections import window_count
from mitski.core.component import Component
from mitski.core.text import cut
from mitski.llm import prompt_format
from mitski.media.emojis import emoji_lib

log = logs.get("reactions")


UNICODE_EMOJI = re.compile(r"[\U0001F000-\U0001FAFF☀-➿⭐⭕←-⇿]️?")
REACT_MOODS = [
    (
        r"\b(lo+l|lma+o+|lmfa+o+|ha(ha)+h?|he(he)+|kek|xd+|dead|im crying)\b|😂|🤣|💀",
        ["kek", "lol", "lmao", "laugh", "xd", "joy", "skull"],
        ["😂", "💀", "😭"],
    ),
    (r"\b(cry|crying|sad|sob|rip)\b|😢|🥲", ["cry", "sob", "sad", "pain"], ["😢", "🥺", "😭"]),
    (r"\b(love|ily|luv|ty|thx|thanks|thank you)\b|<3|❤|💕|🥰", ["heart", "love", "hug", "pat"], ["❤️", "🥰", "💕"]),
    (r"\b(cute|pretty|blush|uwu)\b|😳|🥺", ["blush", "flushed", "shy", "cute"], ["😳", "🥺"]),
    (
        r"\b(gg|win|won|clutch|ace|goated|lets go+|pog)\b|🔥",
        ["pog", "hype", "fire", "yes", "pepeclap"],
        ["🔥", "💯", "🎉"],
    ),
    (r"\b(wtf|huh|bruh|what)\b|\?\?|🤨", ["huh", "what", "think", "stare", "sus"], ["🤨", "👀", "💀"]),
    (r"\b(gn|good night|sleep|eepy)\b|😴", ["sleep", "eepy", "gn", "bed"], ["😴", "💤"]),
    (r"\b(hi+|hey+|hello|yo|gm|good morning)\b|👋", ["wave", "hi", "hello"], ["👋"]),
    (r"\b(ok|okay|bet|sure|agreed|true|real|fr)\b", ["yes", "ok", "thumbs", "nod"], ["👍", "💯"]),
]


class Reactions(Component):
    @staticmethod
    def mood_pick(text, names_of, options):
        for pattern, words, _ in REACT_MOODS:
            if re.search(pattern, text, re.I):
                fits = [o for o in options if any(w in names_of(o).lower() for w in words)]
                return random.choice(fits) if fits else None
        return None

    def default(self, text, guild):
        for pattern, words, fallback in REACT_MOODS:
            if re.search(pattern, text, re.I):
                custom = [e for e in self.app.emojis.ranked(guild) if any(w in e.name.lower() for w in words)]
                if custom and random.random() < 0.6:
                    return random.choice(custom)
                return random.choice(fallback)
        return None

    def parse(self, out, guild):
        out = prompt_format.SPECIAL.sub("", out).strip()
        if not out or out.lower().startswith("none"):
            return None
        find = self.app.emojis.finder(guild)
        m = re.search(r":?(\w{2,32}):?", out)
        if m:
            e = find.custom(m.group(1))
            if e is not None:
                return e
            uni = find.normal(m.group(1)) if ":" in m.group(0) else None
            if uni:
                return uni
        if emoji_lib is not None:
            found = emoji_lib.emoji_list(out)
            if found:
                return found[0]["emoji"]
        m = UNICODE_EMOJI.search(out)
        return m.group(0) if m else None

    async def pick(self, msg, quick=False):
        text = self.messages.text(msg)
        if not text:
            return None
        guild = msg.guild
        if quick and self.app.gpu.locked():
            return self.default(text, guild)
        names = [f":{e.name}:" for e in self.app.emojis.ranked(guild)[:30]]
        her = short_name(self.me)
        prompt = self.llm.fmt.instruct(
            "You pick emoji reactions for messages in a discord chat.",
            f'{short_name(msg.author)} sent this in a discord chat:\n"{cut(text, 300)}"\n\n'
            f"Pick one emoji reaction {her} would add to it."
            + (f" Server emojis she can use: {' '.join(names)}. She can also use any normal emoji." if names else "")
            + " If nothing fits, write none. Answer with only the emoji.",
        )
        try:
            out = await self.llm.generate(prompt, temperature=0.7, n_predict=12, helper=True)
        except Exception:
            log.warning("reaction pick failed", exc_info=True)
            return self.default(text, guild)
        return self.parse(out, guild)

    def allowed(self, channel_id):
        return window_count(self.state.react_times[channel_id], 3600) < self.cfg.MAX_REACTIONS_PER_HOUR

    async def react(self, msg, quick=False, delay=None):
        if not self.cfg.REACTIONS or not self.allowed(msg.channel.id):
            return None
        try:
            emoji = await self.pick(msg, quick)
            if emoji is None:
                return None
            if delay:
                await asyncio.sleep(delay)
            try:
                await msg.add_reaction(emoji)
            except discord.HTTPException as e:
                fallback = self.default(self.messages.text(msg), None) or "👍"
                if getattr(e, "code", None) not in (10014, 50013) or fallback == emoji:
                    raise
                log.warning("reaction %s isn't usable here, using %s instead", emoji, fallback)
                emoji = fallback
                await msg.add_reaction(emoji)
        except discord.HTTPException as e:
            log.warning("reaction failed: %s", e)
            return None
        except Exception:
            log.warning("reaction error", exc_info=True)
            return None
        self.state.react_times[msg.channel.id].append(time.monotonic())
        return emoji

    async def ambient(self, msg):
        await asyncio.sleep(random.uniform(3, 30))
        emoji = await self.react(msg, quick=True)
        if emoji is not None:
            log.info("#%s %s: %s", msg.channel, msg.author, emoji)
