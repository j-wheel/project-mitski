import os

import aiohttp

from mitski.core.texts import say, wording
from mitski.llm.helper import parse_json

DIMENSIONS = ("voice", "in_character", "fits", "human", "boundaries")
ANCHORS = ("1", "3", "5")
KEY_ENV = "MITSKI_JUDGE_KEY"


def wanted(case_judge):
    if case_judge is False:
        return ()
    if isinstance(case_judge, list) and case_judge:
        return tuple(d for d in DIMENSIONS if d in case_judge)
    return DIMENSIONS


def schema(dims):
    one = {
        "type": "object",
        "properties": {
            "why": {"type": "string", "maxLength": 400},
            "score": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        },
        "required": ["why", "score"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": dict.fromkeys(dims, one),
        "required": list(dims),
        "additionalProperties": False,
    }


def persona_text(cfg):
    facts = [
        f"{label} {value}"
        for label, value in (
            ("age", cfg.HER_AGE or ""),
            ("a", cfg.HER_GENDER),
            ("from", cfg.HER_FROM),
            ("lives in", cfg.HER_CITY),
        )
        if value
    ]
    parts = [str(cfg.PERSONA).strip()]
    if facts:
        parts.append(say("judge.facts", facts=", ".join(facts)))
    if str(cfg.STYLE_NOTE or "").strip():
        parts.append(say("judge.style", style=str(cfg.STYLE_NOTE).strip()))
    return "\n".join(parts)


def rubric_text(dims, notes):
    rubrics = wording("judge.dimensions")
    blocks = []
    for d in dims:
        r = rubrics[d]
        lines = [r["what"]] + [f"  {a} = {r[a]}" for a in ANCHORS]
        if notes.get(d):
            lines.append("  " + say("judge.case_note", note=notes[d]))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n\n" + wording("judge.always")


def read_scores(data, dims):
    out = {}
    for d in dims:
        item = (data or {}).get(d)
        if not isinstance(item, dict):
            continue
        try:
            score = int(item.get("score"))
        except (TypeError, ValueError):
            continue
        out[d] = (min(max(score, 1), 5), str(item.get("why") or "").strip())
    return out


class Judge:
    def __init__(self, url=None, model="", runs=1, key=None):
        self.url = (url or "").rstrip("/")
        self.model = model
        self.runs = max(1, int(runs))
        self.key = key if key is not None else os.environ.get(KEY_ENV, "")

    def prompt(self, world, chat, notes, dims):
        her = world.her.name
        user = say(
            "judge.task",
            her=her,
            persona=persona_text(world.app.cfg),
            chat="\n".join(chat),
            rubrics=rubric_text(dims, notes),
        )
        return wording("judge.system"), user

    async def score(self, world, chat, case_judge=None, notes=None):
        dims = wanted(case_judge)
        if not dims or not any(line.startswith(world.her.name + ":") for line in chat):
            return {}
        system, user = self.prompt(world, chat, notes or {}, dims)
        runs = []
        for _ in range(self.runs):
            data = await self.ask(world, system, user, schema(dims))
            got = read_scores(data, dims)
            if got:
                runs.append(got)
        out = {}
        for d in dims:
            got = [r[d] for r in runs if d in r]
            if got:
                out[d] = (sum(s for s, _ in got) / len(got), [w for _, w in got if w])
        return out

    async def ask(self, world, system, user, schema_):
        if not self.url:
            return await world.app.helper.ask_json(system, user, schema_, 900)
        payload = {
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2 if self.runs > 1 else 0.0,
            "max_tokens": 900,
            "response_format": {"type": "json_schema", "json_schema": {"name": "grades", "schema": schema_}},
        }
        if self.model:
            payload["model"] = self.model
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        timeout = aiohttp.ClientTimeout(total=300)
        url = f"{self.url}/v1/chat/completions"
        async with (
            aiohttp.ClientSession(timeout=timeout) as http,
            http.post(url, json=payload, headers=headers) as r,
        ):
            if r.status >= 400:
                raise RuntimeError(f"the judge at {self.url} said {r.status}: {(await r.text())[:200]}")
            body = await r.json()
        return parse_json(body["choices"][0]["message"].get("content") or "")
