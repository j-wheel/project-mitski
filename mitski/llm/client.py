import asyncio
import os
import re
import time
from dataclasses import dataclass, field

import aiohttp

from mitski.core import logs
from mitski.core.component import Component
from mitski.core.metrics import Metrics
from mitski.llm import gpu, prompt_format

log = logs.get("llm")

THINKING = {"temperature": 1.0, "top_p": 0.95, "top_k": 20, "min_p": 0.0, "presence_penalty": 1.0}
REFUSED = re.compile(r"lora|adapter|slot", re.I)


class ModelUnavailable(Exception):
    pass


@dataclass
class Breaker:
    after: int
    pause: float
    failures: int = 0
    paused_until: float = 0.0

    @property
    def open(self):
        return time.monotonic() < self.paused_until

    def failed(self):
        self.failures += 1
        if self.failures >= self.after and not self.open:
            self.paused_until = time.monotonic() + self.pause
            return True
        return False

    def worked(self):
        self.failures = 0
        self.paused_until = 0.0


@dataclass
class ServerInfo:
    slots: int = 1
    lora: list = field(default_factory=list)
    checked: bool = False


class LlamaClient(Component):
    def __init__(self, app):
        super().__init__(app)
        self.fmt = prompt_format.from_config(app.cfg)
        self.fmt_inline = prompt_format.Format(self.fmt.name, "inline")
        self.info = ServerInfo()
        self.breaker = Breaker(self.cfg.LLM_PAUSE_AFTER, self.cfg.LLM_PAUSE_SEC)

    @property
    def qwen(self):
        return self.fmt.name == "qwen"

    @property
    def url(self):
        return self.cfg.llm_url

    def prompt(self, turns, persona=None, notes=None, reopen=False):
        return self.fmt.chat(persona or self.cfg.PERSONA, turns, notes, reopen=reopen)

    def _sampling(self, helper, thinking):
        if thinking:
            return dict(THINKING)
        if helper:
            return {
                "temperature": 0.2,
                "top_p": 0.8 if self.qwen else 1.0,
                "top_k": 20 if self.qwen else 0,
                "min_p": 0.0 if self.qwen else 0.05,
                "presence_penalty": 0.0,
            }
        cfg = self.cfg
        return {
            "temperature": cfg.TEMPERATURE,
            "top_p": cfg.TOP_P,
            "top_k": cfg.TOP_K,
            "min_p": cfg.MIN_P,
            "presence_penalty": cfg.PRESENCE_PENALTY,
        }

    def _payload(self, prompt, temperature, n_predict, json_schema, helper, stop, thinking, lora_scale):
        payload = {
            "prompt": prompt,
            "n_predict": n_predict or self.cfg.MAX_TOKENS,
            **self._sampling(helper, thinking),
            "repeat_penalty": 1.0 if helper else self.cfg.REPEAT_PENALTY,
            "stop": self.fmt.stop + list(stop or []),
            "cache_prompt": True,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if self.info.lora:
            scale = 0.0 if helper else (self.cfg.LORA_SCALE if lora_scale is None else lora_scale)
            payload["lora"] = [{"id": i, "scale": scale} for i in self.info.lora]
        if self.info.slots >= 2:
            payload["id_slot"] = 1 if helper else 0
        if json_schema is not None:
            payload["json_schema"] = json_schema
        return payload

    async def generate(
        self,
        prompt,
        temperature=None,
        n_predict=None,
        json_schema=None,
        helper=False,
        stop=None,
        thinking=False,
        raw=False,
        lora_scale=None,
    ):
        if self.breaker.open:
            Metrics.event("model_paused")
            raise ModelUnavailable(f"llama-server at {self.url} failed {self.breaker.failures} times in a row")
        payload = self._payload(prompt, temperature, n_predict, json_schema, helper, stop, thinking, lora_scale)
        start = time.monotonic()
        async with self.app.gpu.at(None if helper else gpu.REPLY):
            try:
                data = await asyncio.wait_for(self._post(payload), self.cfg.LLM_TIMEOUT_SEC)
            except (aiohttp.ClientError, TimeoutError) as e:
                self._failed(e)
                raise ModelUnavailable(f"{type(e).__name__}: {e}") from e
        self.breaker.worked()
        Metrics.llm_call("think" if thinking else "helper" if helper else "reply", time.monotonic() - start)
        return data if raw else data.get("content", "")

    def _failed(self, error):
        Metrics.event("model_timeout" if isinstance(error, TimeoutError) else "model_error")
        self.app.metrics.count("model failures")
        if self.breaker.failed():
            log.warning(
                "llama-server failed %d times in a row (last: %r), pausing model calls for %ds",
                self.breaker.failures,
                error,
                self.cfg.LLM_PAUSE_SEC,
            )

    async def _post(self, payload):
        async with self.app.http.post(f"{self.url}/completion", json=payload) as r:
            body = (await r.text())[:300] if r.status == 400 else ""
            if body and ("lora" in payload or "id_slot" in payload) and REFUSED.search(body):
                log.warning("llama-server refused the lora/slot settings (%s), going without them", body.strip())
                self.info.lora, self.info.slots = [], 1
                payload.pop("lora", None)
                payload.pop("id_slot", None)
                return await self._post(payload)
            if body:
                log.warning("llama-server said 400: %s", body.strip())
            r.raise_for_status()
            return await r.json()

    async def helper(self, prompt, temperature=None, n_predict=None, json_schema=None):
        return await self.generate(prompt, temperature, n_predict, json_schema, helper=True)

    async def think(self, prompt, budget=800, chunk=160):
        thought, used = "", 0
        while used < budget:
            n = min(chunk, budget - used)
            data = await self.generate(
                prompt + thought, n_predict=n, helper=True, thinking=True, stop=["</think>"], raw=True
            )
            text = data.get("content", "") or ""
            thought += text
            used += int(data.get("tokens_predicted") or n)
            hit_limit = (
                data.get("stop_type") == "limit"
                or data.get("stopped_limit")
                or (
                    "stop_type" not in data
                    and "stopped_limit" not in data
                    and int(data.get("tokens_predicted") or 0) >= n
                )
            )
            if "</think>" in thought or not text or not hit_limit:
                break
        return thought.split("</think>")[0]

    async def _get_json(self, path):
        async with self.app.http.get(f"{self.url}{path}", timeout=aiohttp.ClientTimeout(total=5)) as r:
            return await r.json(content_type=None) if r.status == 200 else None

    async def probe(self):
        try:
            props = await self._get_json("/props") or {}
        except (aiohttp.ClientError, TimeoutError):
            log.error("couldn't reach %s, is llama-server running?", self.url)
            return
        self.info.slots = int(props.get("total_slots") or 1)
        self._check_template(str(props.get("chat_template") or ""))
        try:
            adapters = await self._get_json("/lora-adapters") or []
        except (aiohttp.ClientError, TimeoutError):
            adapters = []
        self.info.lora = (
            [int(a["id"]) for a in adapters if isinstance(a, dict) and "id" in a] if self.cfg.LORA_SCALE > 0 else []
        )
        self.app.vision.extra = self.vision_extra()
        self.info.checked = True
        names = ", ".join(os.path.basename(str(a.get("path", "?"))) for a in adapters if isinstance(a, dict))
        log.info(
            "%s format, %d slot(s)%s | %s",
            self.fmt.name,
            self.info.slots,
            " (chat and helper jobs cache separately)" if self.info.slots >= 2 else "",
            f"lora {names}: her replies at {self.cfg.LORA_SCALE}, helper jobs on the plain model"
            if self.info.lora
            else "no separate lora (merged model): helper jobs use her model too",
        )

    def vision_extra(self):
        extra = {"lora": [{"id": i, "scale": 0.0} for i in self.info.lora]} if self.info.lora else {}
        if self.info.slots >= 2:
            extra["id_slot"] = 1
        if self.qwen:
            extra["chat_template_kwargs"] = {"enable_thinking": False}
        return extra

    def _check_template(self, template):
        if not template:
            return
        if "<|im_start|>" in template:
            found = "qwen"
        elif "[SYSTEM_PROMPT]" in template:
            found = "v7"
        elif "[INST]" in template:
            found = "v3"
        else:
            return
        if (found == "qwen") != self.qwen:
            log.warning(
                "the model on %s looks like it uses the %s format but PROMPT_FORMAT is %r, set PROMPT_FORMAT: %r "
                "in %s if you switched models",
                self.url,
                found,
                self.fmt.name,
                found,
                self.cfg.paths.config.name,
            )

    async def health(self):
        try:
            async with self.app.http.get(f"{self.url}/health") as r:
                return r.status, await r.text()
        except aiohttp.ClientError:
            return None, ""
