import asyncio
import hashlib
import io
import random
import re
import time
from urllib.parse import urlparse

import aiohttp
import discord

from mitski.core import logs
from mitski.core.component import Component
from mitski.core.storage import JsonFile
from mitski.core.text import cut
from mitski.core.texts import say, wording
from mitski.llm.helper import parse_json

log = logs.get("avatar")

HOUR = 3600
REFRESH_EVERY = 6 * HOUR
CHECK_EVERY = 300
FORCE_COOLDOWN = 600
MIN_HOURS = 0.5
MAX_BYTES = 10 * 1024 * 1024
MIN_SIDE = 300
SIZE = 512
TRIES = 8
KEEP_HISTORY = 40
DANBOORU = "https://danbooru.donmai.us"
AGENT = {"User-Agent": "mitski-avatar/1.0"}

AI_HOSTS = (
    "civitai.com",
    "pixai.art",
    "tensor.art",
    "seaart.ai",
    "nightcafe.studio",
    "lexica.art",
    "openart.ai",
    "playgroundai.com",
    "playground.com",
    "mage.space",
    "aibooru.online",
    "novelai.net",
    "prompthero.com",
    "krea.ai",
    "leonardo.ai",
    "midjourney.com",
    "getimg.ai",
    "artbreeder.com",
    "starryai.com",
    "yodayo.com",
    "dreamstudio.ai",
    "stablediffusionweb.com",
    "aiartshop.com",
    "creator.nightcafe.studio",
)
ARTIST_HOSTS = (
    "pximg.net",
    "pixiv.net",
    "twimg.com",
    "x.com",
    "twitter.com",
    "danbooru.donmai.us",
    "safebooru.org",
    "zerochan.net",
    "deviantart.com",
    "wixmp.com",
    "artstation.com",
    "tumblr.com",
    "bsky.app",
)
REPOST_HOSTS = ("pinimg.com", "pinterest.", "wallpaper", "wall.alphacoders", "fandom.com", "wikia.")
AI_WORDS = re.compile(
    r"(?<![a-z])(?:ai[\s_-]*(?:generated|gen|art|artwork|illustration|image|picture|anime|girl|waifu)|"
    r"stable[\s_-]*diffusion|midjourney|niji[\s_-]*journey|novel[\s_-]*ai|dall[\s_-]*e|sdxl|comfyui|"
    r"txt2img|img2img|ai生成|aiイラスト|ai绘画|ai画像)(?![a-z])",
    re.I,
)
BARE_AI = re.compile(r"(?<![a-z])ai(?![a-z])", re.I)
AI_MARKERS = (
    (b"trainedalgorithmicmedia", "its metadata says it was made with AI"),
    (b"novelai", "NovelAI metadata"),
    (b"stable diffusion", "Stable Diffusion metadata"),
    (b"stable-diffusion", "Stable Diffusion metadata"),
    (b"midjourney", "Midjourney metadata"),
    (b"comfyui", "ComfyUI metadata"),
    (b'"class_type"', "ComfyUI workflow in its metadata"),
    (b"invokeai", "InvokeAI metadata"),
    (b"sd-metadata", "Stable Diffusion metadata"),
)
GEN_PARAMS = re.compile(rb"steps: ?\d+.{0,200}sampler: ?\w", re.I | re.S)
BOORU_AI_TAGS = {"ai-generated", "ai-assisted", "ai_generated", "ai_assisted"}


def hours_range(value):
    if isinstance(value, (int, float)):
        lo = hi = float(value)
    else:
        nums = [float(v) for v in list(value or [])[:2]] or [24.0]
        lo, hi = min(nums), max(nums)
    return max(MIN_HOURS, lo), max(MIN_HOURS, hi)


def host_of(url):
    return (urlparse(url or "").hostname or "").lower()


def on_host(url, hosts):
    host = host_of(url)
    return any(host == h or host.endswith("." + h) or h in host for h in hosts)


def ai_in_text(text, character=""):
    text = text or ""
    if AI_WORDS.search(text):
        return True
    return bool(BARE_AI.search(text)) and not BARE_AI.search(character or "")


def ai_markers(data):
    head = (data[:262144] + data[-65536:]).lower() if len(data) > 327680 else data.lower()
    for marker, why in AI_MARKERS:
        if marker in head:
            return why
    if GEN_PARAMS.search(head):
        return "image generation settings in its metadata"
    return None


def rank(candidates, used, character=""):
    out = []
    for c in candidates:
        url, page = c.get("url") or "", c.get("page") or ""
        if not url.startswith(("http://", "https://")) or url in used or (page and page in used):
            continue
        if on_host(url, AI_HOSTS) or on_host(page, AI_HOSTS):
            continue
        if ai_in_text(f"{c.get('title', '')} {url} {page}", character):
            continue
        w, h = int(c.get("width") or 0), int(c.get("height") or 0)
        if (w and w < MIN_SIDE) or (h and h < MIN_SIDE):
            continue
        score = float(c.get("score") or 0)
        if on_host(url, ARTIST_HOSTS) or on_host(page, ARTIST_HOSTS):
            score += 5
        if on_host(url, REPOST_HOSTS) or on_host(page, REPOST_HOSTS):
            score -= 3
        if w and h and 0.75 <= w / h <= 1.35:
            score += 1
        out.append((score + random.random(), c))
    return [c for _, c in sorted(out, key=lambda x: -x[0])]


def square(data, size=SIZE):
    from PIL import Image

    im = Image.open(io.BytesIO(data))
    im.seek(0)
    im = im.convert("RGB")
    w, h = im.size
    if min(w, h) < MIN_SIDE or not 0.4 <= w / h <= 2.5:
        return None
    side = min(w, h)
    left = (w - side) // 2
    top = int((h - side) * 0.15) if h > w else 0
    im = im.crop((left, top, left + side, top + side)).resize((size, size), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "PNG", optimize=True)
    return out.getvalue()


def tag_name(text):
    return re.sub(r"\s+", "_", (text or "").strip().lower())


class SelfProfile(Component):
    def __init__(self, app):
        super().__init__(app)
        self.file = JsonFile(app.cfg.paths.data_file("self_profile.json"))
        self.data = {}
        self.lock = asyncio.Lock()
        self.last_forced = 0.0

    @property
    def auto(self):
        return bool(self.cfg.AVATAR_AUTO)

    @property
    def character(self):
        return str(self.cfg.AVATAR_CHARACTER_NAME or "").strip(), str(self.cfg.AVATAR_CHARACTER_SOURCE or "").strip()

    def load(self):
        self.data = self.file.load()

    def save(self):
        self.file.save(self.data)

    def schedule(self, now=None):
        lo, hi = hours_range(self.cfg.AVATAR_EVERY_H)
        self.data["next_at"] = (now or time.time()) + random.uniform(lo, hi) * HOUR
        self.save()

    def retry_soon(self):
        self.data["next_at"] = time.time() + HOUR
        self.save()

    async def run(self):
        await asyncio.sleep(30)
        while True:
            try:
                if self.cfg.SELF_PROFILE and time.time() - self.data.get("read_at", 0) >= REFRESH_EVERY:
                    await self.refresh()
                if self.auto and all(self.character):
                    if not self.data.get("next_at"):
                        self.schedule()
                    elif time.time() >= self.data["next_at"]:
                        await self.change("it was time for a new one")
            except Exception:
                log.warning("profile check failed", exc_info=True)
            await asyncio.sleep(CHECK_EVERY)

    async def refresh(self):
        me = self.me
        if me is None:
            return
        try:
            profile = await me.profile(with_mutual_guilds=False, with_mutual_friends=False)
        except (discord.HTTPException, TypeError, AttributeError) as e:
            log.info("couldn't read her own profile: %r", e)
            profile = None
        meta = getattr(profile, "metadata", None)
        self.data.update(
            name=str(getattr(me, "global_name", None) or me.name),
            username=str(me.name),
            bio=cut(str(getattr(profile, "bio", None) or getattr(me, "bio", None) or "").strip(), 300),
            pronouns=cut(str(getattr(meta, "pronouns", None) or "").strip(), 40),
            banner=bool(getattr(meta, "banner", None) or getattr(profile, "banner", None)),
            read_at=time.time(),
        )
        avatar = getattr(me, "avatar", None)
        key = getattr(avatar, "key", None) or ""
        if key != self.data.get("avatar_key"):
            self.data.update(avatar_key=key, avatar_desc="", avatar_character="", avatar_source="")
            if avatar is not None:
                self.data["avatar_desc"] = await self._describe(await avatar.read())
        self.save()
        log.info("read her own profile: %s", self.summary())

    async def _describe(self, data):
        vision = self.app.vision
        if not vision.active or not data:
            return ""
        try:
            image, _ = await vision.grabber.picture("image", data)
            if image is None:
                return ""
            text = await vision.client.describe(wording("media.own_avatar"), image, 120)
        except Exception:
            log.info("couldn't look at her own profile picture", exc_info=True)
            return ""
        return cut(re.sub(r"\s+", " ", text or "").strip(), 300)

    def note(self):
        if not self.cfg.SELF_PROFILE or not self.data.get("read_at"):
            return ""
        d = self.data
        bits = [say("persona.own_name", name=d.get("name", ""), username=d.get("username", ""))]
        if d.get("pronouns"):
            bits.append(say("persona.own_pronouns", pronouns=d["pronouns"]))
        bits.append(say("persona.own_bio", bio=d["bio"]) if d.get("bio") else wording("persona.own_no_bio"))
        if d.get("avatar_character"):
            bits.append(
                say(
                    "persona.own_avatar_character",
                    character=d["avatar_character"],
                    source=d.get("avatar_source") or "?",
                    description=d.get("avatar_desc") or wording("persona.own_avatar_unseen"),
                )
            )
        elif d.get("avatar_desc"):
            bits.append(say("persona.own_avatar", description=d["avatar_desc"]))
        elif not d.get("avatar_key"):
            bits.append(wording("persona.own_default_avatar"))
        return wording("persona.own_profile") + " " + "; ".join(bits) + "."

    def summary(self):
        d = self.data
        return ", ".join(
            bit
            for bit in (
                f"{d.get('name')} (@{d.get('username')})",
                f"pronouns {d['pronouns']}" if d.get("pronouns") else "",
                f'bio "{cut(d["bio"], 60)}"' if d.get("bio") else "no bio",
                f"pfp: {cut(d['avatar_desc'], 80)}" if d.get("avatar_desc") else "",
            )
            if bit
        )

    def report(self):
        d = self.data
        name, source = self.character
        lo, hi = hours_range(self.cfg.AVATAR_EVERY_H)
        every = f"every {lo:g}h" if lo == hi else f"every {lo:g} to {hi:g}h"
        lines = [
            f"**profile** {self.summary() or 'not read yet'}",
            f"**pfp character** {name or '(not set)'}" + (f" from {source}" if source else ""),
            f"**auto change** {'on' if self.auto else 'off'}, {every}, from {self.cfg.AVATAR_FROM}"
            + (f", next <t:{int(d['next_at'])}:R>" if self.auto and d.get("next_at") else ""),
        ]
        if d.get("changed_at"):
            lines.append(f"**last change** <t:{int(d['changed_at'])}:R> ({d.get('changed_why', '')})")
        if d.get("avatar_page") or d.get("avatar_url"):
            lines.append(f"**from** <{d.get('avatar_page') or d.get('avatar_url')}>")
        return lines

    async def change(self, why, forced=False):
        name, source = self.character
        if not name:
            return "no character set: `AVATAR_CHARACTER_NAME` / `AVATAR_CHARACTER_SOURCE`, or `.pfp char <name> | <source>`"
        if self.me is None:
            return "not logged in yet"
        if forced and time.monotonic() - self.last_forced < FORCE_COOLDOWN:
            wait = int(FORCE_COOLDOWN - (time.monotonic() - self.last_forced))
            return (
                f"she just changed it, discord only allows a couple of changes in a few minutes. try again in {wait}s"
            )
        if self.lock.locked():
            return "she's already looking for one"
        async with self.lock:
            picked = await self._find(name, source)
            if picked is None:
                self.retry_soon()
                return f"couldn't find a good picture of {name} this time, she'll try again in about an hour"
            image, cand, description = picked
            try:
                await self.me.edit(avatar=image)
            except discord.CaptchaRequired:
                self.schedule()
                return "discord wants a captcha to change her profile picture right now, so she skipped it"
            except discord.HTTPException as e:
                self.retry_soon()
                return (
                    f"discord didn't let her change it ({e.status} {e.text or ''}), she'll try again in about an hour"
                )
            if forced:
                self.last_forced = time.monotonic()
            used = self.data.setdefault("used", [])
            used.extend(u for u in (cand.get("url"), cand.get("page")) if u)
            del used[:-KEEP_HISTORY]
            avatar = getattr(self.me, "avatar", None)
            self.data.update(
                avatar_key=getattr(avatar, "key", None) or hashlib.sha1(image).hexdigest(),
                avatar_desc=description,
                avatar_character=name,
                avatar_source=source,
                avatar_url=cand.get("url", ""),
                avatar_page=cand.get("page", ""),
                changed_at=time.time(),
                changed_why=why,
            )
            self.schedule()
            where = cand.get("page") or cand["url"]
            log.info("changed her profile picture (%s): %s, from %s", why, description or name, where)
            await self.app.relay.post(f"**changed her pfp** ({why}): {description or name}\n<{where}>")
            return f"changed it to {name}: {description or 'no description, vision is off'}\n<{where}>"

    async def _find(self, name, source):
        cands = await self._candidates(name, source)
        used = set(self.data.get("used", []))
        tried = 0
        for cand in rank(cands, used, name):
            if tried >= TRIES:
                break
            tried += 1
            data = await self._download(cand["url"])
            if not data:
                continue
            why = ai_markers(data)
            if why:
                log.info("skipped %s: %s", cand["url"], why)
                continue
            try:
                image = await asyncio.to_thread(square, data)
            except Exception:
                image = None
            if image is None:
                continue
            ok, description = await self._check(image, name, source)
            if ok:
                return image, cand, description
        log.info("no usable picture of %s among %d results (%d tried)", name, len(cands), tried)
        return None

    async def _candidates(self, name, source):
        if self.cfg.AVATAR_FROM == "danbooru":
            found = await self._danbooru(name, source)
            if found:
                return found
            log.info("danbooru had nothing for %s, trying image search", name)
        return await self.app.search.images(say("media.avatar_query", character=name, source=source).strip())

    async def _danbooru(self, name, source):
        try:
            tag = await self._danbooru_tag(name, source)
            if not tag:
                return []
            params = {"tags": tag, "limit": 100}
            async with self.app.http.get(f"{DANBOORU}/posts.json", params=params, headers=AGENT) as r:
                if r.status != 200:
                    log.info("danbooru said %s", r.status)
                    return []
                posts = await r.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError):
            log.info("danbooru search failed", exc_info=True)
            return []
        out = []
        for p in posts if isinstance(posts, list) else []:
            tags = set(str(p.get("tag_string", "")).split())
            if (
                p.get("rating") != "g"
                or tags & BOORU_AI_TAGS
                or p.get("file_ext") not in ("jpg", "jpeg", "png", "webp")
            ):
                continue
            url = p.get("large_file_url") or p.get("file_url")
            if not url:
                continue
            solo = "solo" in tags and str(p.get("tag_string_character", "")).count(" ") == 0
            out.append(
                {
                    "url": url,
                    "page": f"{DANBOORU}/posts/{p.get('id')}",
                    "title": tag,
                    "width": p.get("image_width"),
                    "height": p.get("image_height"),
                    "score": min(10, int(p.get("score") or 0) / 20) + (3 if solo else 0),
                }
            )
        return out

    async def _danbooru_tag(self, name, source):
        params = {"search[query]": tag_name(name), "search[type]": "tag_query", "limit": 10}
        async with self.app.http.get(f"{DANBOORU}/autocomplete.json", params=params, headers=AGENT) as r:
            rows = await r.json(content_type=None) if r.status == 200 else []
        chars = [row for row in rows if isinstance(row, dict) and row.get("category") == 4 and row.get("value")]
        if not chars:
            return None
        want = tag_name(source)
        chars.sort(key=lambda row: (want and want in row["value"], row.get("post_count") or 0), reverse=True)
        return chars[0]["value"]

    async def _download(self, url):
        try:
            timeout = aiohttp.ClientTimeout(total=25)
            async with self.app.http.get(url, timeout=timeout, headers=AGENT) as r:
                if r.status != 200 or not str(r.headers.get("Content-Type", "image")).startswith("image"):
                    return None
                data = bytearray()
                async for chunk in r.content.iter_chunked(65536):
                    data += chunk
                    if len(data) > MAX_BYTES:
                        return None
                return bytes(data)
        except (aiohttp.ClientError, TimeoutError, ValueError):
            return None

    async def _check(self, image, name, source):
        vision = self.app.vision
        if not (self.cfg.AVATAR_CHECK and vision.active):
            return True, ""
        try:
            b64, _ = await vision.grabber.picture("image", image)
            text = await vision.client.describe(
                say("media.avatar_check", character=name, source=source or "its series"), b64, 300
            )
        except Exception:
            log.info("couldn't check a candidate picture", exc_info=True)
            return False, ""
        verdict = parse_json(text) or {}
        reasons = [
            why
            for why, bad in (
                ("not a drawing", verdict.get("drawn") is not True),
                ("not safe for work", verdict.get("safe") is not True),
                ("not one character", verdict.get("solo") is False),
                ("looks AI-made", verdict.get("looks_ai") is not False),
                ("not the character", str(verdict.get("is_character", "")).lower() == "no"),
            )
            if bad
        ]
        if reasons:
            log.info("skipped a picture: %s", ", ".join(reasons))
            return False, ""
        return True, cut(str(verdict.get("description") or "").strip(), 200)
