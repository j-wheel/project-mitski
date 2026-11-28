import asyncio
import os
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field

import aiohttp

from mitski.core import logs
from mitski.core.component import Component
from mitski.core.metrics import Metrics
from mitski.llm import gpu, prompt_format

log = logs.get("llm")

THINKING = {"temperature": 1.0, "top_p": 0.95, "top_k": 20, "min_p": 0.0, "presence_penalty": 1.0}
REFUSED = re.compile(r"lora|adapter|slot", re.I)
BACKGROUND_TIMEOUT = 3
SLOW_SEC = 20.0
SLOW_TOKENS_PER_SEC = 5.0
CHARS_PER_TOKEN = 3.0
CTX_MARGIN = 256
SMALL_CTX = 12288
SENTENCE_END = re.compile(r"[.!?…](?=\s|$)")


def lora_label(path):
    name = os.path.basename(path)
    try:
        made = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(path)))
    except OSError:
        return name
    return f"{name} ({made})"


def tokens_guess(text):
    return int(len(text or "") / CHARS_PER_TOKEN) + 1


def stopped_at_limit(data, n=None):
    if not isinstance(data, dict):
        return False
    if "stop_type" in data or "stopped_limit" in data:
        return data.get("stop_type") == "limit" or bool(data.get("stopped_limit"))
    return n is not None and int(data.get("tokens_predicted") or 0) >= n


def drop_unfinished(text):
    lines = [ln for ln in (text or "").rstrip().split("\n") if ln.strip()]
    if len(lines) > 1:
        return "\n".join(lines[:-1])
    ends = list(SENTENCE_END.finditer(text or ""))
    return text[: ends[-1].end()].strip() if ends else (text or "").strip()


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
    n_ctx: int = 0


class LlamaClient(Component):
    def __init__(self, app):
        super().__init__(app)
        self.fmt = prompt_format.from_config(app.cfg)
        self.fmt_inline = prompt_format.Format(self.fmt.name, "inline")
        self.info = ServerInfo()
        self.breaker = Breaker(self.cfg.LLM_PAUSE_AFTER, self.cfg.LLM_PAUSE_SEC)
        self.slot_of = OrderedDict()
        self.cache_stats = {"calls": 0, "prompt": 0, "cached": 0}

    @property
    def qwen(self):
        return self.fmt.name == "qwen"

    @property
    def url(self):
        return self.cfg.llm_url

    def prompt(self, turns, persona=None, notes=None, reopen=False, n_predict=None):
        persona = persona or self.cfg.PERSONA
        text = self.fmt.chat(persona, turns, notes, reopen=reopen)
        room = self.room(n_predict or self.cfg.MAX_TOKENS)
        if room is None or tokens_guess(text) <= room:
            return text
        turns, dropped = list(turns), 0
        while len(turns) > 2 and tokens_guess(text) > room:
            turns, dropped = turns[1:], dropped + 1
            text = self.fmt.chat(persona, turns, notes, reopen=reopen)
        log.info(
            "her prompt didn't fit the model's %d-token context, left out the %d oldest messages",
            self.info.n_ctx,
            dropped,
        )
        return text

    def room(self, n_predict):
        return self.info.n_ctx - n_predict - CTX_MARGIN if self.info.n_ctx else None

    def room_chars(self, reserved_tokens, default):
        room = self.room(reserved_tokens)
        return default if room is None else max(2000, min(default, int(room * CHARS_PER_TOKEN)))

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

    def slot_for(self, helper, key=None):
        slots = self.info.slots
        if slots < 2:
            return None
        if helper:
            return slots - 1
        chat = slots - 1
        if chat == 1:
            return 0
        key = "-" if key is None else key
        if key in self.slot_of:
            self.slot_of.move_to_end(key)
            return self.slot_of[key]
        taken = set(self.slot_of.values())
        free = [s for s in range(chat) if s not in taken]
        if free:
            slot = free[0]
        else:
            _, slot = self.slot_of.popitem(last=False)
        self.slot_of[key] = slot
        return slot

    def cache_report(self):
        c = self.cache_stats
        if not c["calls"]:
            return "prompt cache: no replies yet"
        share = c["cached"] / max(1, c["prompt"] + c["cached"])
        return (
            f"prompt cache: {share:.0%} of her reply prompts came from cache over {c['calls']} replies "
            f"({c['prompt'] // c['calls']} new tokens per reply on average), {self.info.slots} slot(s)"
        )

    def _note_cache(self, data, helper):
        t = data.get("timings") or {} if isinstance(data, dict) else {}
        new, cached = int(t.get("prompt_n") or 0), int(t.get("cache_n") or 0)
        if not (new or cached):
            return
        if not helper:
            self.cache_stats["calls"] += 1
            self.cache_stats["prompt"] += new
            self.cache_stats["cached"] += cached
        log.debug("%s prompt: %d new tokens, %d from cache", "helper" if helper else "reply", new, cached)

    def _payload(self, prompt, temperature, n_predict, json_schema, helper, stop, thinking, lora_scale, cache_key=None):
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
        slot = self.slot_for(helper, cache_key)
        if slot is not None:
            payload["id_slot"] = slot
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
        cache_key=None,
    ):
        if self.breaker.open:
            Metrics.event("model_paused")
            raise ModelUnavailable(f"llama-server at {self.url} failed {self.breaker.failures} times in a row")
        payload = self._payload(
            prompt, temperature, n_predict, json_schema, helper, stop, thinking, lora_scale, cache_key
        )
        room = self.room(payload["n_predict"])
        if room is not None and tokens_guess(prompt) > room:
            log.warning(
                "a %s prompt is about %d tokens, more than fits the model's %d-token context with %d for the answer: "
                "start llama-server with a bigger -c",
                "helper" if helper else "reply",
                tokens_guess(prompt),
                self.info.n_ctx,
                payload["n_predict"],
            )
        background = helper and gpu.PRIORITY.get() == gpu.BACKGROUND
        timeout = self.cfg.LLM_TIMEOUT_SEC * (BACKGROUND_TIMEOUT if background else 1)
        start = time.monotonic()
        async with self.app.gpu.at(None if helper else gpu.REPLY):
            sent = time.monotonic()
            try:
                data = await asyncio.wait_for(self._post(payload), timeout)
            except (aiohttp.ClientError, TimeoutError) as e:
                self._failed(e, background, time.monotonic() - sent, tokens_guess(prompt))
                raise ModelUnavailable(f"{type(e).__name__}: {e}" if str(e) else type(e).__name__) from e
        self.breaker.worked()
        took = time.monotonic() - sent
        self._note_cache(data, helper)
        if took >= SLOW_SEC:
            self._slow(took, data, "think" if thinking else "helper" if helper else "reply")
        Metrics.llm_call("think" if thinking else "helper" if helper else "reply", time.monotonic() - start)
        return data if raw else data.get("content", "")

    def _slow(self, took, data, kind):
        t = data.get("timings") or {} if isinstance(data, dict) else {}
        prompt_n, prompt_rate = int(t.get("prompt_n") or 0), float(t.get("prompt_per_second") or 0)
        made_n, made_rate = int(t.get("predicted_n") or 0), float(t.get("predicted_per_second") or 0)
        hint = ""
        if made_n and made_rate and made_rate < SLOW_TOKENS_PER_SEC:
            hint = (
                ": that's very slow generation. the GPU may be busy with something else, or out of VRAM (on windows "
                "the driver then quietly spills into system RAM): try a smaller -c, or close what else uses the GPU"
            )
        log.info(
            "a %s call took %.0fs (prompt %d tokens at %.0f/s, wrote %d at %.1f/s)%s",
            kind,
            took,
            prompt_n,
            prompt_rate,
            made_n,
            made_rate,
            hint,
        )

    def _failed(self, error, background=False, took=0.0, prompt_tokens=0):
        Metrics.event("model_timeout" if isinstance(error, TimeoutError) else "model_error")
        self.app.metrics.count("model failures")
        if background:
            log.info(
                "a background model call gave up after %.0fs (%s, prompt about %d tokens), she'll get to it later",
                took,
                type(error).__name__,
                prompt_tokens,
            )
            return
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
            if "</think>" in thought or not text or not stopped_at_limit(data, n):
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
        settings = props.get("default_generation_settings") or {}
        self.info.n_ctx = int(settings.get("n_ctx") or props.get("n_ctx") or 0)
        if self.info.n_ctx and self.info.n_ctx < SMALL_CTX:
            log.warning(
                "the model's context is %d tokens per slot: her memory notes and longer chats need more, start "
                "llama-server with -c %d or more (that's split between %d slot(s))",
                self.info.n_ctx,
                SMALL_CTX * 2 * self.info.slots,
                self.info.slots,
            )
        elif self.info.n_ctx:
            log.info("context: %d tokens per slot", self.info.n_ctx)
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
        names = ", ".join(lora_label(str(a.get("path", "?"))) for a in adapters if isinstance(a, dict))
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
            extra["id_slot"] = self.slot_for(helper=True)
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
