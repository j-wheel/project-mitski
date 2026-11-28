import asyncio
import html
import re
import time
from collections import deque

from mitski.chat.messages import clean, short_name
from mitski.core import logs
from mitski.core.collections import BoundedDict, window_count
from mitski.core.component import Component
from mitski.core.text import cut
from mitski.core.texts import say

try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None

log = logs.get("search")

PROVIDERS = ("ddg", "searxng", "brave", "google")
LOOKUP_HINT = re.compile(
    r"\?|\b(what|whats|who|whos|when|where|which|how (much|many|long|old)|did|does|is there|google|look (it|that) up|"
    r"search|news|latest|newest|update|patch|release|score|won|price|cost|weather|wiki)\b",
    re.I,
)
SEARCH_DECIDE = {
    "type": "object",
    "properties": {"search": {"type": "boolean"}, "query": {"type": "string", "maxLength": 100}},
    "required": ["search", "query"],
    "additionalProperties": False,
}
SEARCH_ANSWER = {
    "type": "object",
    "properties": {"found": {"type": "boolean"}, "answer": {"type": "string", "maxLength": 400}},
    "required": ["found", "answer"],
    "additionalProperties": False,
}
CACHE_SEC = 600


def strip_html(text):
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


class WebSearch(Component):
    def __init__(self, app):
        super().__init__(app)
        self.times = deque()
        self.cache = BoundedDict(300)
        self.lookups = BoundedDict(500)
        self.provider = self._pick_provider()

    @property
    def searxng_url(self):
        return str(self.cfg.SEARXNG_URL or "").rstrip("/")

    def _pick_provider(self):
        name = str(self.cfg.SEARCH_PROVIDER or "").strip().lower()
        problem = None
        if name and name not in PROVIDERS:
            problem = f"unknown SEARCH_PROVIDER {name!r}"
        elif name == "ddg" and DDGS is None:
            problem = "SEARCH_PROVIDER is ddg but the ddgs package isn't installed (pip install ddgs)"
        elif name == "brave" and not self.cfg.SEARCH_KEY:
            problem = "SEARCH_PROVIDER is brave but SEARCH_KEY is empty"
        elif name == "google" and not (self.cfg.SEARCH_KEY and self.cfg.SEARCH_CX):
            problem = "SEARCH_PROVIDER is google but SEARCH_KEY/SEARCH_CX are empty"
        if problem:
            log.warning("%s, searching is off", problem)
            return ""
        return name

    async def search(self, query):
        now = time.monotonic()
        key = query.lower()
        cached = self.cache.get(key)
        if cached and now - cached[0] < CACHE_SEC:
            return cached[1]
        if window_count(self.times, 3600, now) >= self.cfg.SEARCH_MAX_PER_HOUR:
            log.info("hourly search limit reached")
            return ""
        self.times.append(now)
        try:
            results = await self._fetch(query)
        except Exception:
            log.warning("%s search for %r failed", self.provider, query, exc_info=True)
            return ""
        rows = [f"- {cut(strip_html(t), 90)}: {cut(strip_html(s), 220)}" for t, s in results if t or s]
        text = "\n".join(rows[:5])
        self.cache[key] = (now, text)
        return text

    async def _fetch(self, query):
        if self.provider == "ddg":
            return await self._ddg(query)
        if self.provider == "searxng":
            params = {"q": query, "format": "json"}
            async with self.app.http.get(f"{self.searxng_url}/search", params=params) as r:
                r.raise_for_status()
                rows = (await r.json()).get("results") or []
            return [(r.get("title", ""), r.get("content", "")) for r in rows[:5]]
        if self.provider == "brave":
            headers = {"X-Subscription-Token": self.cfg.SEARCH_KEY, "Accept": "application/json"}
            url = "https://api.search.brave.com/res/v1/web/search"
            async with self.app.http.get(url, params={"q": query, "count": 5}, headers=headers) as r:
                r.raise_for_status()
                rows = ((await r.json()).get("web") or {}).get("results") or []
            return [(r.get("title", ""), r.get("description", "")) for r in rows[:5]]
        if self.provider == "google":
            params = {"key": self.cfg.SEARCH_KEY, "cx": self.cfg.SEARCH_CX, "q": query, "num": 5}
            async with self.app.http.get("https://www.googleapis.com/customsearch/v1", params=params) as r:
                r.raise_for_status()
                rows = (await r.json()).get("items") or []
            return [(r.get("title", ""), r.get("snippet", "")) for r in rows[:5]]
        return []

    async def images(self, query, n=40):
        if not self.provider:
            log.info("no SEARCH_PROVIDER, can't search for images")
            return []
        try:
            rows = await self._image_rows(query, n)
        except Exception:
            log.warning("%s image search for %r failed", self.provider, query, exc_info=True)
            return []
        return [r for r in rows if r.get("url")]

    async def _image_rows(self, query, n):
        if self.provider == "ddg":
            rows = await asyncio.wait_for(
                asyncio.to_thread(lambda: DDGS().images(query, safesearch="on", max_results=n)), 30
            )
            return [
                {
                    "url": r.get("image"),
                    "page": r.get("url"),
                    "title": r.get("title", ""),
                    "width": r.get("width"),
                    "height": r.get("height"),
                }
                for r in rows or []
            ]
        if self.provider == "searxng":
            params = {"q": query, "format": "json", "categories": "images", "safesearch": 2}
            async with self.app.http.get(f"{self.searxng_url}/search", params=params) as r:
                r.raise_for_status()
                rows = (await r.json()).get("results") or []
            return [{"url": r.get("img_src"), "page": r.get("url"), "title": r.get("title", "")} for r in rows[:n]]
        if self.provider == "brave":
            headers = {"X-Subscription-Token": self.cfg.SEARCH_KEY, "Accept": "application/json"}
            url = "https://api.search.brave.com/res/v1/images/search"
            params = {"q": query, "count": min(n, 100), "safesearch": "strict"}
            async with self.app.http.get(url, params=params, headers=headers) as r:
                r.raise_for_status()
                rows = (await r.json()).get("results") or []
            return [
                {"url": (r.get("properties") or {}).get("url"), "page": r.get("url"), "title": r.get("title", "")}
                for r in rows
            ]
        if self.provider == "google":
            out = []
            for start in (1, 11, 21):
                params = {
                    "key": self.cfg.SEARCH_KEY,
                    "cx": self.cfg.SEARCH_CX,
                    "q": query,
                    "searchType": "image",
                    "safe": "active",
                    "num": 10,
                    "start": start,
                }
                async with self.app.http.get("https://www.googleapis.com/customsearch/v1", params=params) as r:
                    r.raise_for_status()
                    rows = (await r.json()).get("items") or []
                out += [
                    {
                        "url": r.get("link"),
                        "page": (r.get("image") or {}).get("contextLink"),
                        "title": r.get("title", ""),
                        "width": (r.get("image") or {}).get("width"),
                        "height": (r.get("image") or {}).get("height"),
                    }
                    for r in rows
                ]
                if len(rows) < 10 or len(out) >= n:
                    break
            return out
        return []

    async def _ddg(self, query):
        failure = None
        for backend in ({}, {"backend": "auto"}, {"backend": "lite"}, {"backend": "html"}):
            try:
                rows = await asyncio.wait_for(
                    asyncio.to_thread(lambda kw=backend: DDGS().text(query, max_results=5, **kw)), 20
                )
            except TypeError:
                continue
            except Exception as e:
                failure = e
                continue
            if rows:
                return [(r.get("title", ""), r.get("body", "")) for r in rows]
        if failure is not None:
            log.warning("ddg search failed: %r", failure)
        return []

    async def answer(self, query, said, name):
        found = await self.search(query)
        log.info("%r -> %d results", query, len(found.splitlines()))
        if not found:
            return ""
        today = self.app.clock.now().strftime("%A %Y-%m-%d")
        her = short_name(self.me)
        summary = await self.app.helper.ask_json(
            say("search.read_results_system", her=her),
            say("search.read_results", name=name, said=cut(said, 300), query=query, today=today, found=found, her=her),
            SEARCH_ANSWER,
            320,
        )
        answer = cut(str((summary or {}).get("answer") or "").strip(), 400)
        await self.app.relay.post(
            f"**googled** `{query}`\n**answer:** {answer or '(nothing clear)'}\n-# {cut(found, 1200)}"
        )
        if summary and summary.get("found") and answer:
            return say("search.found", query=query, answer=answer)
        return say("search.not_found", query=query)

    async def quick_lookup(self, target, msgs):
        if not self.provider or target is None or target.author.id == self.me.id:
            return ""
        if target.id in self.lookups:
            return self.lookups[target.id]
        result = ""
        text = clean(self.messages.with_mentions(target))
        if len(text) >= 8 and LOOKUP_HINT.search(text):
            result = await self._decide_and_answer(target, msgs, text)
        self.lookups[target.id] = result
        return result

    async def _decide_and_answer(self, target, msgs, text):
        her = short_name(self.me)
        name = self.messages.call(target.author)
        today = self.app.clock.now().strftime("%A %Y-%m-%d")
        recent = "\n".join(f"{self.messages.call(m.author)}: {cut(self.messages.text(m), 200)}" for m in msgs[-6:])
        decide = await self.app.helper.ask_json(
            say("search.decide_system", her=her, today=today),
            say("search.decide", recent=recent, name=name, text=cut(text, 300)),
            SEARCH_DECIDE,
            80,
        )
        if decide is None:
            log.info("the helper model didn't answer, skipping the search")
            return ""
        query = str(decide.get("query") or "").strip(" \"'`.")
        if not decide.get("search") or not 3 <= len(query) <= 100:
            return ""
        return await self.answer(query, text, name)
