import time
from collections import defaultdict, deque

from mitski.chat.messages import short_name
from mitski.core import logs
from mitski.core.component import Component
from mitski.core.text import cut
from mitski.core.texts import say, wording

log = logs.get("thoughts")

WINDOW = 14
GAP_SEC = 45
KEEP_UNSAID = 3
SCHEMA = {
    "type": "object",
    "properties": {
        "thought": {"type": "string", "maxLength": 200},
        "target": {"type": "integer", "minimum": 0, "maximum": WINDOW},
        "motivation": {"type": "integer", "minimum": 1, "maximum": 5},
    },
    "required": ["thought", "target", "motivation"],
    "additionalProperties": False,
}


class InnerThoughts(Component):
    def __init__(self, app):
        super().__init__(app)
        self.heard_since = defaultdict(int)
        self.last_at = {}
        self.unsaid = defaultdict(lambda: deque(maxlen=KEEP_UNSAID))
        self.thinking = set()

    @property
    def on(self):
        return bool(self.cfg.INNER_THOUGHTS)

    def heard(self, msg):
        cid = msg.channel.id
        self.heard_since[cid] += 1
        if cid in self.thinking or self.heard_since[cid] < max(1, int(self.cfg.THOUGHT_EVERY)):
            return
        now = time.monotonic()
        if now - self.last_at.get(cid, 0) < GAP_SEC * self.app.ambient.busy_factor(cid):
            return
        if self.llm.breaker.open or not self.app.ambient.may_join(cid):
            return
        self.heard_since[cid] = 0
        self.last_at[cid] = now
        self.thinking.add(cid)
        self.app.tasks.spawn(self.consider(msg.channel), name=f"thought-{cid}")

    async def consider(self, channel):
        cid = channel.id
        try:
            window = await self._window(channel)
            if not window or window[-1].author.id == self.me.id:
                return
            got = await self.app.helper.ask_json(*self._prompt(window, cid), SCHEMA, 260)
            if not got:
                return
            thought = cut(str(got.get("thought") or "").strip(), 200)
            motivation = int(got.get("motivation") or 1)
            pick = int(got.get("target") or 0)
            log.info("#%s: (%d/5) %s", getattr(channel, "name", cid), motivation, thought or "(nothing)")
            if not thought:
                return
            if motivation >= int(self.cfg.THOUGHT_MIN_MOTIVATION) and self.app.ambient.may_join(cid):
                target = window[pick - 1] if 1 <= pick <= len(window) else None
                if target is None or target.author.id == self.me.id:
                    target = next((m for m in reversed(window) if m.author.id != self.me.id), window[-1])
                self.unsaid[cid].clear()
                self.app.pipeline.join_in(channel, target, inner=thought, aim=target.id)
            elif motivation >= 3:
                self.unsaid[cid].append(thought)
        except Exception:
            log.warning("thinking about #%s failed", getattr(channel, "name", cid), exc_info=True)
        finally:
            self.thinking.discard(cid)

    async def _window(self, channel):
        context = self.app.context
        msgs = await context.recent_history(channel, WINDOW + 6)
        msgs = list(reversed(context.within_gap([m for m in msgs if self.messages.usable(m)])))
        return msgs[-WINDOW:]

    def _prompt(self, window, cid):
        her = short_name(self.me) if self.me else "mitski"
        lines = []
        for i, m in enumerate(window, 1):
            who = wording("thoughts.you") if m.author.id == self.me.id else self.messages.call(m.author)
            lines.append(f"[{i}] {who}: {cut(self.messages.text(m), 300)}")
        unsaid = list(self.unsaid[cid])
        earlier = say("thoughts.earlier", thoughts=" / ".join(unsaid)) + "\n\n" if unsaid else ""
        mood = self.app.feelings.mood_words() or wording("thoughts.mood_normal")
        persona = self.app.policy.tamed(getattr(window[-1], "channel", None), self.cfg.PERSONA)
        system = say("thoughts.system", her=her, persona=persona)
        user = say("thoughts.task", her=her, chat="\n".join(lines), earlier=earlier, mood=mood)
        return system, user
