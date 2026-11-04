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
            f"You read google results for {her} and pull out what she needs to reply. Answer with JSON: "
            f'{{"found": true/false, "answer": "..."}}.',
            f'{name} said: "{cut(said, 300)}"\nShe googled: {query}\nToday is {today}.\n\n'
            f"Results:\n{found}\n\nIn 1 or 2 short sentences, write the facts from these results that answer it or help "
            f"her reply, with the specific names, numbers and dates. Only the facts themselves, don't mention {her} or "
            f"what she should say. If they don't actually answer it, found is false.",
            SEARCH_ANSWER,
            160,
        )
        answer = cut(str((summary or {}).get("answer") or "").strip(), 400)
        await self.app.relay.post(
            f"**googled** `{query}`\n**answer:** {answer or '(nothing clear)'}\n-# {cut(found, 1200)}"
        )
        if summary and summary.get("found") and answer:
            return f'You googled "{query}": {answer} Say it in your own words, no links.'
        return f"You googled \"{query}\" but didn't find a clear answer, so don't make one up."

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
            f"You decide whether {her}, a person chatting on discord, should quickly google something before she "
            f'replies. Today is {today}. Answer with JSON: {{"search": true/false, "query": "..."}}.',
            f'Recent chat:\n{recent}\n\n{name} just said: "{cut(text, 300)}"\n\n'
            f"Search only when a good reply needs current or specific facts she can't just know: news, game "
            f"updates and patches, esports or sports results, prices, release dates, real people, specific facts, "
            f"or when someone asks her to look something up. Chatting, opinions, feelings, jokes and common "
            f"knowledge don't need a search. If it does, write a short google query.",
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
