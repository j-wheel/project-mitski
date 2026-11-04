import asyncio
import io
import random
import re

import aiohttp
import discord

from mitski.chat.messages import short_name
from mitski.chat.patterns import NO_PINGS
from mitski.core import logs
from mitski.core.component import Component
from mitski.core.text import cut

log = logs.get("extras")


GIF_MOODS = [
    (r"\b(lo+l|lma+o+|lmfa+o+|ha(ha)+h?|he(he)+|kek|xd+)\b|😂|🤣", ["laughing", "giggle", "laugh"]),
    (r"><|\b(uwu|owo|blush|cute|shy)\b|😳|🥺|>\.<", ["blush", "shy", "embarrassed"]),
    (r"\b(cry|crying|sad|sob)\b|😭|😢|🥲", ["crying", "sad", "pout cry"]),
    (r"\b(love|ily|luv)\b|<3|❤|💕|🥰|😘", ["heart", "love", "hug"]),
    (r"\b(wtf|huh|bruh|what)\b|\?\?|🤨|😐", ["confused", "what", "stare"]),
    (r"\b(gg|win|won|clutch|ace|goated|lets go+)\b|🔥", ["celebrate", "victory", "hype"]),
    (r"\b(mad|angry|stfu|shut up|hmph)\b|😡|😤|💢", ["angry", "pout", "hmph"]),
    (r"\b(hi+|hey+|hello|yo|heyy+)\b|👋", ["wave", "hello"]),
    (r"\b(gn|sleep|sleepy|tired|eepy)\b|😴|💤", ["sleepy", "yawn"]),
]
GIF_GENERIC = ["happy", "vibing", "dance", "smug", "wink"]
GIF_UPLOAD_MAX = 8 * 1024 * 1024


class Extras(Component):
    def __init__(self, app):
        super().__init__(app)
        self.warned = set()

    async def pick_sticker(self, guild, lines):
        stickers = self.app.emojis.stickers(guild)[:40]
        if not stickers:
            return None
        text = " ".join(lines)

        def about(s):
            return self.app.vision.sticker_caption(s.id) or s.description or ""

        def sticker_words(s):
            return f"{s.name} {about(s)} {s.emoji or ''}"

        if self.app.gpu.locked():
            return self.app.reactions.mood_pick(text, sticker_words, stickers)
        her = short_name(self.me)
        listing = "\n".join(
            f"{i}. {s.name}" + (f" ({cut(about(s), 90)})" if about(s) else "") for i, s in enumerate(stickers, 1)
        )
        prompt = self.llm.fmt.instruct(
            "You pick stickers for messages in a discord chat.",
            f'{her} just said this in a discord chat:\n"{cut(text, 300)}"\n\n'
            f"Which of these stickers would she send right after it?\n{listing}\n0. none of them fit\n\n"
            f"Answer with only the number.",
        )
        try:
            out = await self.llm.generate(prompt, temperature=0.5, n_predict=6, helper=True)
        except Exception:
            log.warning("sticker pick failed", exc_info=True)
            return self.app.reactions.mood_pick(text, sticker_words, stickers)
        m = re.search(r"\d+", out)
        if not m:
            return None
        i = int(m.group(0))
        return stickers[i - 1] if 1 <= i <= len(stickers) else None

    def gif_query(self, text):
        for pattern, terms in GIF_MOODS:
            if re.search(pattern, text, re.I):
                return f"{self.cfg.GIF_STYLE} {random.choice(terms)}".strip()
        if random.random() < 0.3:
            return f"{self.cfg.GIF_STYLE} {random.choice(GIF_GENERIC)}".strip()
        return None

    async def find_gif(self, text):
        if not self.cfg.GIPHY_KEY:
            return None
        query = self.gif_query(text)
        if not query:
            return None
        params = {"api_key": self.cfg.GIPHY_KEY, "q": query, "limit": 25, "rating": self.cfg.GIF_RATING, "lang": "en"}
        try:
            async with self.app.http.get("https://api.giphy.com/v1/gifs/search", params=params) as r:
                if r.status != 200:
                    log.info("giphy %s: %s", r.status, await r.text())
                    return None
                results = (await r.json()).get("data") or []
        except aiohttp.ClientError as e:
            log.warning("giphy failed: %s", e)
            return None
        if not results:
            return None
        pick = random.choice(results)
        images = pick.get("images") or {}
        link = images.get("original", {}).get("url") or pick.get("url")
        small = next(
            (
                images[k]["url"]
                for k in ("downsized_medium", "downsized", "fixed_height")
                if images.get(k, {}).get("url") and int(images[k].get("size") or 0) <= GIF_UPLOAD_MAX
            ),
            None,
        )
        return {"link": link, "file": small or link, "title": pick.get("slug") or "gif"}

    def perms(self, channel):
        guild = getattr(channel, "guild", None)
        me = getattr(guild, "me", None) if guild is not None else None
        if me is None:
            return None
        try:
            return channel.permissions_for(me)
        except Exception:
            return None

    def can_embed(self, channel):
        p = self.perms(channel)
        return p is None or bool(p.embed_links)

    def can_attach(self, channel):
        p = self.perms(channel)
        return p is None or bool(p.attach_files)

    def warn_once(self, channel, what, text):
        if (channel.id, what) not in self.warned:
            self.warned.add((channel.id, what))
            log.info("#%s: %s", getattr(channel, "name", channel.id), text)

    async def download_gif(self, url):
        async with self.app.http.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
            if r.status != 200:
                return None
            data = bytearray()
            async for chunk in r.content.iter_chunked(65536):
                data += chunk
                if len(data) > GIF_UPLOAD_MAX:
                    return None
        return bytes(data)

    async def maybe_gif(self, channel, lines):
        if random.random() >= self.cfg.GIF_CHANCE:
            return None, None
        embed = self.can_embed(channel)
        upload = not embed and self.cfg.GIF_UPLOAD and self.can_attach(channel)
        if not embed and not upload:
            self.warn_once(
                channel,
                "gif",
                "no 'embed links' permission"
                + (" or 'attach files'" if self.cfg.GIF_UPLOAD else "")
                + ", so she doesn't send gifs here",
            )
            return None, None
        if upload:
            self.warn_once(channel, "gif", "no 'embed links' permission, so she uploads gifs as files here")
        try:
            gif = await self.find_gif("\n".join(lines))
            if not gif:
                return None, None
            if upload:
                data = await self.download_gif(gif["file"])
                if not data:
                    return None, None
                name = re.sub(r"[^\w-]+", "-", gif["title"])[:60].strip("-") or "gif"
                await asyncio.sleep(random.uniform(0.8, 2.5))
                async with self.app.voice.typing_in(channel):
                    msg = await channel.send(
                        file=discord.File(io.BytesIO(data), filename=f"{name}.gif"), allowed_mentions=NO_PINGS
                    )
                return gif["link"], msg
            await asyncio.sleep(random.uniform(0.8, 2.5))
            msg = await channel.send(gif["link"], allowed_mentions=NO_PINGS)
            return gif["link"], msg
        except Exception:
            log.warning("gif failed", exc_info=True)
            return None, None

    async def after_reply(self, channel, lines):
        guild = getattr(channel, "guild", None)
        if (
            (guild is not None or self.app.emojis.external_ok(None, "stickers"))
            and self.cfg.STICKER_CHANCE > 0
            and random.random() < self.cfg.STICKER_CHANCE
        ):
            try:
                sticker = await self.pick_sticker(guild, lines)
                if sticker is not None:
                    await asyncio.sleep(random.uniform(0.8, 2.5))
                    msg = await channel.send(stickers=[sticker], allowed_mentions=NO_PINGS)
                    return f"sticker: {sticker.name}", msg
            except Exception:
                log.warning("sticker failed", exc_info=True)
        return await self.maybe_gif(channel, lines)
