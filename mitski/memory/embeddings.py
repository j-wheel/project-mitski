import base64
import hashlib
import json
import math
import struct

import aiohttp

from mitski.core import logs
from mitski.core.storage import JsonFile, write_atomic

log = logs.get("embeddings")

QUERY_TASK = (
    "Given a message in a chat, retrieve memories about the person and past conversations that are relevant to it"
)


def _key(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:20]


def _pack(vec):
    return base64.b64encode(struct.pack(f"<{len(vec)}e", *vec)).decode("ascii")


def _unpack(s):
    raw = base64.b64decode(s)
    return list(struct.unpack(f"<{len(raw) // 2}e", raw))


def _norm(vec, dims):
    if dims and len(vec) > dims:
        vec = vec[:dims]
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b, strict=False))


class Embedder:
    def __init__(self, cfg, get_http):
        self.url = str(cfg.MEMORY_EMBED_URL or "").rstrip("/")
        self.model = str(cfg.MEMORY_EMBED_MODEL or "").strip()
        self.key = cfg.MEMORY_EMBED_KEY
        self.dims = cfg.MEMORY_EMBED_DIMS
        prefix = cfg.MEMORY_EMBED_QUERY_PREFIX
        self.query_prefix = f"Instruct: {QUERY_TASK}\nQuery: " if prefix is None else str(prefix)
        self.get_http = get_http
        self.file = JsonFile(cfg.paths.data_file("memory_vectors.json"), indent=None)
        self.cache = {}
        self.dirty = False
        self.broken = None
        self.fails = 0

    @property
    def active(self):
        return bool(self.url) and self.broken is None

    def status(self):
        if not self.url:
            return "keywords + tags (no MEMORY_EMBED_URL)"
        return (
            f"off ({self.broken})"
            if self.broken
            else f"embeddings via {self.url}" + (f" ({self.model})" if self.model else "")
        )

    def load(self):
        data = self.file.load()
        if isinstance(data, dict) and data.get("dims") == self.dims and data.get("model") == self.model:
            self.cache = data.get("v", {})

    def snapshot(self, keep=None):
        if keep is not None:
            alive = {_key(t) for t in keep}
            self.cache = {k: v for k, v in self.cache.items() if k in alive}
        self.dirty = False
        return json.dumps({"model": self.model, "dims": self.dims, "v": self.cache})

    def write(self, text):
        write_atomic(self.file.path, text)

    async def _call(self, texts):
        payload = {"input": texts}
        if self.model:
            payload["model"] = self.model
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        async with self.get_http().post(
            f"{self.url}/v1/embeddings", json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
        ) as r:
            if r.status != 200:
                raise RuntimeError(f"embedding server {r.status}: {(await r.text())[:200]}")
            data = await r.json(content_type=None)
        rows = sorted(data.get("data") or [], key=lambda x: x.get("index", 0))
        return [_norm(row["embedding"], self.dims) for row in rows]

    async def docs(self, texts):
        if not self.active:
            return None
        missing = list(dict.fromkeys(t for t in texts if _key(t) not in self.cache))
        try:
            for i in range(0, len(missing), 32):
                batch = missing[i : i + 32]
                for t, v in zip(batch, await self._call(batch), strict=False):
                    self.cache[_key(t)] = _pack(v)
                    self.dirty = True
            self.fails = 0
        except Exception as e:
            self._failed(e)
            return None
        return [_unpack(self.cache[_key(t)]) for t in texts]

    async def query(self, text):
        if not self.active:
            return None
        try:
            v = (await self._call([self.query_prefix + text]))[0]
            self.fails = 0
            return v
        except Exception as e:
            self._failed(e)
            return None

    def _failed(self, e):
        self.fails += 1
        log.info("embedding failed (%r)%s", e, ", using keywords for now" if self.fails < 5 else "")
        if self.fails >= 5:
            self.broken = f"failed 5 times in a row, last: {e!r}"[:200]
            log.info("embeddings turned off: %s", self.broken)
