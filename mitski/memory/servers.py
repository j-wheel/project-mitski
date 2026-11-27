import time
from collections import Counter

from mitski.core import logs
from mitski.core.component import Component
from mitski.core.storage import JsonFile
from mitski.core.text import cut
from mitski.core.texts import say, wording
from mitski.llm import gpu

log = logs.get("servers")

FACTS_MAX = 25
IN_PROMPT = 8
MIN_GAP_SEC = 6 * 3600
READ_MSGS = 120
CHAT_CHARS = 9000
SCHEMA = {
    "type": "object",
    "properties": {
        "new_facts": {"type": "array", "maxItems": 5, "items": {"type": "string", "maxLength": 140}},
        "wrong": {"type": "array", "maxItems": 5, "items": {"type": "integer"}},
    },
    "required": ["new_facts", "wrong"],
    "additionalProperties": False,
}


class ServerNotes(Component):
    def __init__(self, app):
        super().__init__(app)
        self.file = JsonFile(app.cfg.paths.data_file("servers.json"))
        self.data = {}
        self.heard = Counter()
        self.running = set()

    def load(self):
        self.data = self.file.load()

    def facts(self, guild):
        return (self.data.get(str(getattr(guild, "id", ""))) or {}).get("facts") or []

    def blurb(self, guild):
        facts = self.facts(guild)[-IN_PROMPT:] if self.cfg.SERVER_NOTES else []
        if not facts:
            return ""
        return (
            (say("memory.server_known", name=guild.name) + " ") + "; ".join(f["text"].rstrip(".") for f in facts) + "."
        )

    def heard_in(self, msg):
        guild = getattr(msg, "guild", None)
        if not self.cfg.SERVER_NOTES or guild is None or guild.id in self.running:
            return
        self.heard[guild.id] += 1
        entry = self.data.get(str(guild.id)) or {}
        due = self.heard[guild.id] >= self.cfg.SERVER_NOTES_EVERY or not entry
        if due and time.time() - entry.get("at", 0) >= MIN_GAP_SEC and self.heard[guild.id] >= 20:
            self.heard[guild.id] = 0
            self.running.add(guild.id)
            self.app.tasks.spawn(self.update(guild, msg.channel), name=f"server-notes-{guild.id}")

    def _about(self, guild):
        lines = [f"Server: {guild.name}"]
        if getattr(guild, "description", None):
            lines.append(say("memory.server_description", description=cut(guild.description, 300)))
        count = getattr(guild, "member_count", None) or len(getattr(guild, "members", []) or [])
        if count:
            lines.append(say("memory.server_members", count=count))
        channels = [c for c in getattr(guild, "channels", []) if getattr(c, "name", None) and hasattr(c, "topic")]
        listed = [
            f"#{c.name}" + (f" ({cut(c.topic, 100)})" if getattr(c, "topic", None) else "") for c in channels[:25]
        ]
        if listed:
            lines.append("Channels: " + ", ".join(listed))
        return "\n".join(lines)

    async def update(self, guild, channel):
        gpu.background()
        her = self.messages.own_names()
        try:
            msgs = [m async for m in channel.history(limit=READ_MSGS)][::-1]
            me = self.me.id if self.me else None
            chat, size = [], 0
            for m in reversed(msgs):
                text = self.messages.text(m)
                if not text or (m.author.bot and m.author.id != me):
                    continue
                who = "you" if m.author.id == me else self.messages.call(m.author)
                line = f"{who}: {cut(text, 220)}"
                size += len(line) + 1
                if size > CHAT_CHARS:
                    break
                chat.insert(0, line)
            facts = self.facts(guild)
            known = "\n".join(f"{i}. {f['text']}" for i, f in enumerate(facts, 1)) or "(nothing yet)"
            out = await self.app.helper.ask_json(
                wording("memory.server_notes_system"),
                (
                    say(
                        "memory.server_notes",
                        about=self._about(guild),
                        known=known,
                        channel=getattr(channel, "name", "?"),
                    )
                    + "\n"
                )
                + "\n".join(chat)
                + ("\n\n" + wording("memory.server_notes_task")),
                SCHEMA,
                500,
            )
            if not out:
                return
            changes = []
            wrong = {int(i) for i in out.get("wrong") or [] if isinstance(i, int)}
            kept = [f for i, f in enumerate(facts, 1) if i not in wrong]
            if len(kept) < len(facts):
                changes.append(f"- {len(facts) - len(kept)} out of date")
            have = {f["text"].lower() for f in kept}
            for text in out.get("new_facts") or []:
                text = cut(str(text).strip(), 140)
                if text and text.lower() not in have and not any(n and n.lower() in text.lower() for n in her):
                    kept.append({"text": text, "t": time.time()})
                    have.add(text.lower())
                    changes.append(f"+ {text}")
            self.data[str(guild.id)] = {"name": guild.name, "facts": kept[-FACTS_MAX:], "at": time.time()}
            self.file.save(self.data)
            if changes:
                log.info("%s: %s", guild.name, " | ".join(changes))
                await self.app.relay.post(f"**server memory · {guild.name}**\n" + "\n".join(changes))
        except Exception:
            log.warning("server notes for %s failed", getattr(guild, "name", guild), exc_info=True)
        finally:
            self.running.discard(guild.id)
