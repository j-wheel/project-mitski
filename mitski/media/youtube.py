import asyncio
import re

import aiohttp

from mitski.chat.patterns import YT_URL
from mitski.core import logs
from mitski.core.collections import BoundedDict
from mitski.core.component import Component
from mitski.core.text import cut, squash

try:
    from youtube_transcript_api import YouTubeTranscriptApi as YTApi
except ImportError:
    YTApi = None

log = logs.get("youtube")


class YouTube(Component):
    def __init__(self, app):
        super().__init__(app)
        self.cache = BoundedDict(300)

    @property
    def transcripts(self):
        return YTApi is not None and self.cfg.YT_TRANSCRIPT_CHARS > 0

    def transcript(self, vid):
        if YTApi is None:
            return ""
        try:
            if hasattr(YTApi, "fetch"):
                api = YTApi()
                try:
                    fetched = api.fetch(vid, languages=("en", "en-US", "en-GB"))
                except Exception:
                    fetched = next(iter(api.list(vid))).fetch()
                text = " ".join(s.text for s in fetched)
            else:
                text = " ".join(r["text"] for r in YTApi.get_transcript(vid))
        except Exception as e:
            log.info("no transcript for %s: %s", vid, type(e).__name__)
            return ""
        return re.sub(r"\s+", " ", text).strip()[: self.cfg.YT_TRANSCRIPT_CHARS]

    async def info(self, vid, want_summary=False):
        info = self.cache.get(vid)
        if info is None:
            info = {"title": "", "author": "", "desc": "", "summary": None}
            self.cache[vid] = info
            try:
                params = {"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"}
                async with self.app.http.get("https://www.youtube.com/oembed", params=params) as r:
                    if r.status == 200:
                        data = await r.json(content_type=None)
                        info["title"] = data.get("title", "")
                        info["author"] = data.get("author_name", "")
                if self.cfg.YOUTUBE_KEY:
                    params = {"part": "snippet", "id": vid, "key": self.cfg.YOUTUBE_KEY}
                    async with self.app.http.get("https://www.googleapis.com/youtube/v3/videos", params=params) as r:
                        if r.status == 200:
                            items = (await r.json()).get("items") or []
                            if items:
                                info["desc"] = items[0]["snippet"].get("description", "")
            except (aiohttp.ClientError, TimeoutError) as e:
                log.warning("info for %s failed: %r", vid, e)
            except Exception:
                log.warning("info for %s failed", vid, exc_info=True)
        if want_summary and info["summary"] is None and info["title"] and self.cfg.YT_TRANSCRIPT_CHARS > 0:
            info["summary"] = ""
            transcript = await asyncio.to_thread(self.transcript, vid)
            if transcript:
                summary = await self.app.helper.ask_text(
                    "You summarize youtube videos for someone who hasn't watched them.",
                    f'Transcript of the youtube video "{info["title"]}" by {info["author"]}:\n\n{transcript}\n\n'
                    f"In 2 or 3 short sentences: what is the video about and what happens in it? Plain text only.",
                    160,
                )
                if summary:
                    info["summary"] = cut(summary, 600)
                    log.info("%s: %s", info["title"], info["summary"])
        return info

    async def prefetch(self, msgs):
        if not self.cfg.YOUTUBE:
            return
        vids = list(dict.fromkeys(v for m in msgs[-10:] for v in YT_URL.findall(m.content)))
        for vid in vids[-4:]:
            await self.info(vid)

    async def notes(self, msgs):
        if not self.cfg.YOUTUBE:
            return ""
        found = []
        for m in reversed(msgs[-6:]):
            for vid in YT_URL.findall(m.content):
                if vid not in (v for _, v in found):
                    found.append((m, vid))
        out = []
        for i, (m, vid) in enumerate(found[:2]):
            info = await self.info(vid, want_summary=(i == 0))
            if not info["title"]:
                continue
            who = "You" if m.author.id == self.me.id else self.messages.call(m.author)
            line = f'{who} shared a youtube video: "{info["title"]}" by {info["author"]}.'
            if info.get("summary"):
                line += f" You watched it, it's about: {info['summary']}"
            elif info.get("desc"):
                line += f" Its description: {cut(squash(info['desc']), 300)}"
            out.append(line)
        return "\n".join(out)
