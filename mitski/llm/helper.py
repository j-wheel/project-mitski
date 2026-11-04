import asyncio
import json
import re
import time
from dataclasses import dataclass

import aiohttp

from mitski.core import logs
from mitski.core.metrics import Metrics
from mitski.llm import prompt_format
from mitski.llm.client import ModelUnavailable

log = logs.get("helper")


def parse_json(text):
    text = prompt_format.SPECIAL.sub("", prompt_format.strip_thinking(text or "")).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


@dataclass
class Answer:
    text: str
    thought: str = ""


class HelperModel:
    def __init__(self, app):
        self.app = app
        cfg = app.cfg
        self.url = str(cfg.NOTES_URL or "").rstrip("/")
        if self.url == cfg.llm_url:
            self.url = ""
        self.model = str(cfg.NOTES_MODEL or "").strip()
        self.key = cfg.NOTES_KEY
        self.json_mode = "json_schema"
        self.think_tokens = cfg.MEMORY_THINK_TOKENS
        self.lock = app.gpu if not self.url else asyncio.Semaphore(1)

    @property
    def external(self):
        return bool(self.url)

    @property
    def think_on(self):
        return self.app.cfg.MEMORY_THINK and not self.url and self.app.llm.fmt.can_think

    async def ask(self, system, user_text, schema=None, max_tokens=700, think=False):
        if self.url:
            return Answer(await self._ask_openai(system, user_text, schema, max_tokens))
        fmt = self.app.llm.fmt
        prompt, thought = fmt.instruct(system, user_text), ""
        if think and self.think_on:
            base = fmt.instruct(system, user_text, think=True)
            try:
                thought = (await self.app.llm.think(base, self.think_tokens)).strip()
            except Exception:
                log.warning("thinking failed, answering without it", exc_info=True)
                thought = ""
            if thought:
                prompt = fmt.after_thinking(base, thought)
        text = await self.app.llm.helper(prompt, temperature=0.2, n_predict=max_tokens, json_schema=schema)
        return Answer(text, thought)

    async def ask_json(self, system, user_text, schema, max_tokens=400, think=False):
        try:
            return parse_json((await self.ask(system, user_text, schema, max_tokens, think)).text)
        except Exception as e:
            self._failed(e)
            return None

    async def ask_text(self, system, user_text, max_tokens=200):
        try:
            out = (await self.ask(system, user_text, None, max_tokens)).text
        except Exception as e:
            self._failed(e)
            return ""
        return re.sub(r"\s+", " ", prompt_format.SPECIAL.sub("", prompt_format.strip_thinking(out or ""))).strip()

    def _failed(self, error):
        Metrics.event("helper failed")
        self.app.metrics.count("helper failures")
        if isinstance(error, ModelUnavailable):
            log.info("helper call skipped: %s", error)
        else:
            log.warning("helper call failed", exc_info=error)

    async def _ask_openai(self, system, user_text, schema, max_tokens):
        payload = {
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_text}],
            "temperature": 0.2,
            "max_tokens": max_tokens + 100,
        }
        if self.model:
            payload["model"] = self.model
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        if schema is None:
            modes = [None]
        elif self.json_mode == "json_object":
            modes = ["json_object"]
        else:
            modes = ["json_schema", "json_object"]
        status, body = 0, ""
        for mode in modes:
            payload.pop("response_format", None)
            if mode == "json_schema":
                payload["response_format"] = {"type": "json_schema", "json_schema": {"name": "reply", "schema": schema}}
            elif mode == "json_object":
                payload["response_format"] = {"type": "json_object"}
            start = time.monotonic()
            async with (
                self.lock,
                self.app.http.post(
                    f"{self.url}/v1/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=180),
                ) as r,
            ):
                status = r.status
                if status == 200:
                    data = await r.json(content_type=None)
                    Metrics.llm_call("helper", time.monotonic() - start)
                    if mode is not None:
                        self.json_mode = mode
                    return ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
                body = (await r.text())[:300]
            if mode == "json_schema" and status in (400, 422, 500):
                continue
            break
        raise RuntimeError(f"notes server {status}: {body}")
