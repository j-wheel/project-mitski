import re
import time
from collections import deque

from mitski.core import logs
from mitski.core.collections import window_count
from mitski.core.component import Component
from mitski.core.storage import JsonFile
from mitski.core.text import cut
from mitski.core.texts import say, wording
from mitski.llm import gpu

log = logs.get("knowledge")

KEPT = 300
IN_PROMPT = 3
RETRY_DAYS = 30
SCHEMA = {
    "type": "object",
    "properties": {"known": {"type": "boolean"}, "what": {"type": "string", "maxLength": 220}},
    "required": ["known", "what"],
    "additionalProperties": False,
}
KIND = re.compile(r"\s*\(([^)]*)\)\s*$")


def topic_key(topic):
    return re.sub(r"\s+", " ", KIND.sub("", str(topic or "")).strip().lower())


class Knowledge(Component):
    def __init__(self, app):
        super().__init__(app)
        self.file = JsonFile(app.cfg.paths.data_file("knowledge.json"))
        self.data = {}
        self.times = deque()
        self.pending = set()

    def load(self):
        self.data = self.file.load()

    @property
    def on(self):
        return bool(self.cfg.LOOK_UP_INTERESTS and self.app.search.provider)

    def want(self, topics, name=""):
        if not self.on or not isinstance(topics, list):
            return
        for topic in topics[:2]:
            key = topic_key(topic)
            if len(key) < 3 or key in self.pending:
                continue
            known = self.data.get(key)
            if known and (known.get("what") or time.time() - known.get("t", 0) < RETRY_DAYS * 86400):
                continue
            if window_count(self.times, 3600, time.monotonic()) >= self.cfg.LOOK_UP_PER_HOUR:
                return
            self.times.append(time.monotonic())
            self.pending.add(key)
            topic = str(topic).strip()
            self.app.downtime.later(
                f"look-up-{key[:20]}",
                lambda t=topic: self.learn(t, name),
                f"looking up {topic} (for {name or 'someone'})",
            )

    async def learn(self, topic, name=""):
        key = topic_key(topic)
        try:
            gpu.background()
            found = await self.app.search.search(topic)
            out = None
            if found:
                out = await self.app.helper.ask_json(
                    wording("search.note_system"),
                    say("search.note", topic=topic, found=found),
                    SCHEMA,
                    200,
                )
            what = cut(str((out or {}).get("what") or "").strip(), 220) if (out or {}).get("known") else ""
            self.data[key] = {"topic": KIND.sub("", topic).strip(), "what": what, "t": time.time(), "for": name}
            while len(self.data) > KEPT:
                self.data.pop(min(self.data, key=lambda k: self.data[k].get("t", 0)))
            self.file.save(self.data)
            if what:
                log.info("looked up %s (for %s): %s", topic, name or "someone", what)
                await self.app.relay.post(f"**looked up** {topic} (for {name or 'someone'})\n{what}")
            else:
                log.info("looked up %s, nothing clear", topic)
        except Exception:
            log.warning("looking up %r failed", topic, exc_info=True)
        finally:
            self.pending.discard(key)

    def note(self, text):
        low = f" {re.sub(r'[^a-z0-9 ]+', ' ', (text or '').lower())} "
        hits = [v for k, v in self.data.items() if v.get("what") and f" {re.sub(r'[^a-z0-9 ]+', ' ', k)} " in low][
            :IN_PROMPT
        ]
        if not hits:
            return ""
        return (
            (wording("search.looked_up_before") + " ")
            + " | ".join(f"{v['topic']}: {v['what'].rstrip('.')}" for v in hits)
            + "."
        )
