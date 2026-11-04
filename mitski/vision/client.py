import asyncio
import re

import aiohttp

from mitski.core import logs

log = logs.get("vision")

NOT_SUPPORTED = re.compile(
    r"image input is not supported|mmproj|multimodal|vision.*not|not.*vision|does not support image", re.I
)
TIMEOUT = aiohttp.ClientTimeout(total=120)


class VisionUnsupported(RuntimeError):
    pass


class VisionClient:
    def __init__(self, app):
        cfg = app.cfg
        self.app = app
        self.url = str(cfg.VISION_URL or "").rstrip("/") or cfg.llm_url
        self.model = str(cfg.VISION_MODEL or "").strip()
        self.key = cfg.VISION_KEY
        self.same_server = self.url == cfg.llm_url
        self.lock = app.gpu if self.same_server else asyncio.Semaphore(2)
        self.extra = {}

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.key}"} if self.key else {}

    async def supports_images(self):
        try:
            async with self.app.http.get(f"{self.url}/props", timeout=aiohttp.ClientTimeout(total=5)) as r:
                if r.status != 200:
                    return True
                modalities = (await r.json(content_type=None)).get("modalities") or {}
        except (aiohttp.ClientError, TimeoutError, ValueError):
            return True
        return "vision" not in modalities or bool(modalities["vision"])

    def _payload(self, prompt, image_b64, max_tokens):
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                    ],
                }
            ],
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }
        if self.same_server:
            payload.update(self.extra)
        if self.model:
            payload["model"] = self.model
        return payload

    async def describe(self, prompt, image_b64, max_tokens=160):
        payload = self._payload(prompt, image_b64, max_tokens)
        async with self.lock:
            status, body, data = await self._post(payload)
            if status == 400 and self.same_server and self.extra:
                log.info("server refused %s, going without them: %s", sorted(self.extra), body[:200])
                for k in self.extra:
                    payload.pop(k, None)
                self.extra = {}
                status, body, data = await self._post(payload)
        if status != 200:
            if status in (400, 404, 415, 422, 500, 501) and NOT_SUPPORTED.search(body):
                raise VisionUnsupported(body.strip()[:120])
            raise RuntimeError(f"vision server {status}: {body}")
        return ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""

    async def _post(self, payload):
        url = f"{self.url}/v1/chat/completions"
        async with self.app.http.post(url, json=payload, headers=self.headers, timeout=TIMEOUT) as r:
            if r.status == 200:
                return 200, "", await r.json(content_type=None)
            return r.status, (await r.text())[:300], {}
