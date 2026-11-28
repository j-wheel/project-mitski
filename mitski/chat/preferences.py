import json
import time

from mitski.core import logs
from mitski.core.component import Component

log = logs.get("preferences")

MIN_CHARS = 2


class Preferences(Component):
    def __init__(self, app):
        super().__init__(app)
        self.path = app.cfg.paths.data_file("preferences.jsonl")
        self.count = 0

    @property
    def on(self):
        return bool(self.cfg.PREFERENCE_LOG)

    def keep(self, reply, rejected, chosen, kind, source="her"):
        if not self.on or reply is None or reply.ctx is None or not reply.ctx.turns:
            return
        rejected, chosen = "\n".join(rejected or []).strip(), "\n".join(chosen or []).strip()
        if len(rejected) < MIN_CHARS or len(chosen) < MIN_CHARS or rejected == chosen:
            return
        if reply.minors or any(self.memory.opted_out(m.author) for m in reply.ctx.everything):
            return
        row = {
            "t": round(time.time()),
            "kind": kind,
            "source": source,
            "system": reply.persona,
            "turns": [[role, text] for role, text in reply.ctx.turns],
            "notes": reply.notes,
            "rejected": rejected,
            "chosen": chosen,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            log.warning("couldn't save a preference pair", exc_info=True)
            return
        self.count += 1
        log.debug("[%s] kept a %s pair (%s)", reply.tag, kind, source)
