import aiohttp

from mitski.core import logs

log = logs.get("rerank")

MAX_FAILS = 5


class Reranker:
    def __init__(self, cfg, get_http):
        self.url = str(cfg.RERANK_URL or "").rstrip("/")
        self.get_http = get_http
        self.fails = 0
        self.broken = None

    @property
    def active(self):
        return bool(self.url) and self.broken is None

    def status(self):
        if not self.url:
            return "off (no RERANK_URL)"
        return f"off ({self.broken})" if self.broken else f"on, {self.url}"

    async def rank(self, query, docs, top_n=None):
        if not self.active or not docs:
            return None
        payload = {"query": query, "documents": list(docs), "top_n": top_n or len(docs)}
        try:
            async with self.get_http().post(
                f"{self.url}/v1/rerank", json=payload, timeout=aiohttp.ClientTimeout(total=20)
            ) as r:
                if r.status != 200:
                    raise RuntimeError(f"rerank server {r.status}: {(await r.text())[:200]}")
                data = await r.json(content_type=None)
        except Exception as e:
            self.fails += 1
            log.info("reranking failed (%r)", e)
            if self.fails >= MAX_FAILS:
                self.broken = f"failed {MAX_FAILS} times in a row, last: {e!r}"[:200]
                log.warning("reranking turned off: %s", self.broken)
            return None
        self.fails = 0
        rows = data.get("results") if isinstance(data, dict) else data
        out = [(int(row["index"]), float(row.get("relevance_score", row.get("score", 0.0)))) for row in rows or []]
        if out and len({round(s, 6) for _, s in out}) == 1 and len(out) > 1:
            log.warning("the reranker gave every document the same score, its gguf may be broken: turning it off")
            self.broken = "every score was the same (a broken gguf?)"
            return None
        return sorted(out, key=lambda x: -x[1])
