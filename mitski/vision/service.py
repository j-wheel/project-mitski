import asyncio
import time
from collections import deque

import aiohttp

from mitski.core import logs
from mitski.core.collections import BoundedDict, window_count
from mitski.core.storage import JsonFile
from mitski.llm import gpu
from mitski.vision import prompts
from mitski.vision.client import VisionClient, VisionUnsupported
from mitski.vision.frames import FrameGrabber
from mitski.vision.items import find_items, safe_url, sticker_item

log = logs.get("vision")

CACHE_VERSION = 2
CACHE_KEEP = 3000
RETRY_AFTER = 600
HOUR = 3600


class Vision:
    def __init__(self, app):
        cfg = app.cfg
        self.app = app
        self.cfg = cfg
        self.client = VisionClient(app)
        self.grabber = FrameGrabber(cfg.VISION_FRAMES, cfg.VISION_MAX_SIDE)
        self.file = JsonFile(cfg.paths.data_file("vision_cache.json"), indent=None)
        self.max_bytes = int(cfg.VISION_MAX_MB * 1024 * 1024)
        self.cache = {}
        self.meta = {}
        self.details = BoundedDict(200)
        self.inflight = {}
        self.times = deque()
        self.index_times = deque()
        self.warned = 0.0
        self.dirty = False
        self.broken = (
            "pillow isn't installed (pip install pillow)" if cfg.VISION and not self.grabber.available else None
        )

    @property
    def url(self):
        return self.client.url

    @property
    def extra(self):
        return self.client.extra

    @extra.setter
    def extra(self, value):
        self.client.extra = value

    @property
    def active(self):
        return self.cfg.VISION and not self.broken

    def load(self):
        raw = self.file.load()
        self.cache = {k: v for k, v in raw.items() if "tag" in v and v.get("v") == CACHE_VERSION}

    def save_if_dirty(self):
        if not self.dirty:
            return
        tagged = sorted(((k, v) for k, v in self.cache.items() if "tag" in v), key=lambda kv: kv[1]["t"])
        self.file.save(dict(tagged[-CACHE_KEEP:]))
        self.dirty = False

    def status(self):
        if not self.cfg.VISION:
            return "off"
        if self.broken:
            return f"off ({self.broken})"
        model = f" ({self.client.model})" if self.client.model else ""
        return f"on via {self.url}{model}" + (" + ffmpeg" if self.grabber.ffmpeg else "")

    async def check(self):
        if self.active and not await self.client.supports_images():
            self._unsupported("")

    def _unsupported(self, detail):
        self.broken = (
            f"the server at {self.url} can't see images{f' ({detail})' if detail else ''}, start llama-server "
            f"with --mmproj <projector.gguf>, or point VISION_URL at a vision model"
        )
        log.info("turned off: %s", self.broken)

    def items(self, m):
        return find_items(m, self.cfg.VISION_MAX_PER_MSG, bool(self.grabber.ffmpeg))

    def tags(self, m):
        out = []
        for it in self.items(m):
            seen = self.cache.get(it.key, {}).get("tag")
            if it.kind == "sticker":
                desc = seen or self.meta.get(it.key)
                out.append(f"[sticker: {it.name}" + (f" ({desc})" if desc else "") + "]")
                continue
            label = it.kind + (" (spoiler)" if it.spoiler else "")
            text = seen or it.hint
            out.append(f"[{label}: {text}]" if text else f"[{label}]")
        return out

    def sticker_caption(self, sticker_id):
        key = f"s{sticker_id}"
        return self.cache.get(key, {}).get("tag") or self.meta.get(key)

    async def prefetch(self, msgs, skip_author=None):
        if not self.active:
            return
        todo = [
            self.look(it, m)
            for m in list(msgs)[-self.cfg.VISION_CONTEXT_MSGS :]
            if skip_author is None or m.author.id != skip_author
            for it in self.items(m)
        ]
        if todo:
            await asyncio.gather(*todo, return_exceptions=True)

    def warm(self, m):
        if self.active and self.items(m):
            self.app.tasks.spawn(self.prefetch([m]), name=f"vision-warm-{m.id}")

    async def look(self, it, m=None, background=False):
        entry = self.cache.get(it.key)
        if entry and ("tag" in entry or time.time() - entry.get("fail", 0) < RETRY_AFTER):
            return
        task = self.inflight.get(it.key)
        if task is None:
            task = asyncio.get_running_loop().create_task(self._look(it, m, background))
            self.inflight[it.key] = task
            task.add_done_callback(lambda _t, key=it.key: self.inflight.pop(key, None))
        await asyncio.shield(task)

    def _budget(self, background=False):
        limit = self.cfg.VISION_INDEX_PER_HOUR if background else self.cfg.VISION_MAX_PER_HOUR
        if limit <= 0:
            return True
        times = self.index_times if background else self.times
        if window_count(times, HOUR, time.time()) >= limit:
            if not background and time.time() - self.warned > RETRY_AFTER:
                self.warned = time.time()
                log.info("hourly limit reached (%s/hour), raise VISION_MAX_PER_HOUR or set it to 0", limit)
            return False
        times.append(time.time())
        return True

    def _failed(self, it):
        self.cache[it.key] = {"fail": time.time()}

    async def _look(self, it, m, background=False):
        try:
            if it.kind == "sticker":
                await self._sticker_meta(it)
            if not it.viewable or not self.active:
                return
            image, n_frames = await self.grabber.picture(it.kind, await self._download(it))
            if image is None:
                self._failed(it)
                return
            if not self._budget(background):
                return
            prompt = prompts.caption_prompt(it, n_frames, prompts.said_with(m), self.meta.get(it.key, ""))
            text = prompts.tidy_caption(await self.client.describe(prompt, image))
            if not text:
                self._failed(it)
                return
            self.cache[it.key] = {"tag": text, "t": time.time(), "v": CACHE_VERSION}
            self.dirty = True
            log.info("%s: %s", it.kind, text)
        except VisionUnsupported as e:
            self._unsupported(str(e))
            self._failed(it)
        except Exception:
            log.warning("couldn't look at %s %s", it.kind, it.key, exc_info=True)
            self._failed(it)

    async def _sticker_meta(self, it):
        if it.key in self.meta or it.source is None:
            return
        self.meta[it.key] = ""
        try:
            full = await it.source[1].fetch()
        except Exception:
            log.debug("couldn't fetch sticker %s", it.key, exc_info=True)
            return
        self.meta[it.key] = (getattr(full, "description", "") or "").strip()[:100]

    async def _download(self, it):
        where, src = it.source
        if where == "attachment" and it.size > self.max_bytes:
            log.info("%s is too big (%s kb)", it.key, it.size // 1024)
            return None
        if where in ("attachment", "sticker"):
            return await src.read()
        if where != "url" or not safe_url(src):
            return None
        async with self.app.http.get(src, timeout=aiohttp.ClientTimeout(total=20), allow_redirects=False) as r:
            if r.status != 200:
                return None
            data = bytearray()
            async for chunk in r.content.iter_chunked(65536):
                data += chunk
                if len(data) > self.max_bytes:
                    return None
            return bytes(data)

    async def detail(self, msgs, question):
        if not self.active:
            return ""
        it = next((i for m in msgs for i in self.items(m) if i.viewable), None)
        if it is None:
            return ""
        key = (it.key, question.strip().lower()[:80])
        if key in self.details:
            return self.details[key]
        image, _ = await self.grabber.picture(it.kind, await self._download(it))
        if image is None:
            return ""
        try:
            raw = await self.client.describe(prompts.detail_prompt(it, question), image, max_tokens=320)
        except VisionUnsupported as e:
            self._unsupported(str(e))
            return ""
        text = prompts.tidy_detail(raw)
        self.details[key] = text
        log.info("closer look: %s", text)
        return text

    async def index_stickers(self, guilds):
        if not (self.active and self.cfg.VISION_INDEX_STICKERS):
            return
        gpu.background()
        await asyncio.sleep(30)
        limit = self.cfg.VISION_INDEX_PER_HOUR
        for guild in guilds:
            for sticker in list(getattr(guild, "stickers", [])):
                if not self.active:
                    return
                while self.app.gpu.locked() or (
                    limit > 0 and window_count(self.index_times, HOUR, time.time()) >= limit
                ):
                    await asyncio.sleep(30)
                it = sticker_item(sticker)
                if it.key in self.cache or not getattr(sticker, "available", True):
                    continue
                if getattr(sticker, "description", None):
                    self.meta[it.key] = sticker.description[:100]
                if it.fmt == "lottie":
                    continue
                await self.look(it, background=True)
                await asyncio.sleep(20)
