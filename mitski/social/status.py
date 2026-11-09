"""Her discord custom status: the line and emoji under her name, rewritten by her own model every so often."""

import asyncio
import random
import re
import time

import discord

from mitski.chat.policy import SAFE_REMINDER, explicit, tame, tone_problem
from mitski.core import logs
from mitski.core.clock import time_phrase
from mitski.core.component import Component
from mitski.core.storage import JsonFile
from mitski.llm.helper import parse_json

log = logs.get("status")

STATUS_MAX = 128
START_DELAY = (60, 180)
RETRY_SEC = 600
RECENT_KEPT = 12
TOKENS = 120
TEMPERATURE = 0.95
SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "minLength": 1, "maxLength": STATUS_MAX},
        "emoji": {"type": "string", "minLength": 1, "maxLength": 16},
    },
    "required": ["status", "emoji"],
    "additionalProperties": False,
}
INSTRUCTIONS = (
    "You're changing your discord custom status, the little line people see under your name. Write what you'd really "
    "put there right now: a passing thought, a mood, a dumb joke, something you're into, what you're up to. It's not "
    "a message to anyone. Type it the way you type in chat, usually just a few words, and never more than "
    f"{STATUS_MAX} characters. Pick one normal emoji that goes with it. No @mentions, no links, no hashtags, nothing "
    "sexual, and don't name people you know. Answer only with JSON."
)
EVERYONE_SEES = f"Your status shows in every server you're in, so it has to be fine for all of them. {SAFE_REMINDER}"
NOT_FOR_A_STATUS = re.compile(r"@|https?://|discord\.gg/", re.I)
_MOD = "[\U0001f3fb-\U0001f3ff]?️?"
_PIC = "[\U0001f000-\U0001faff☀-➿⬀-⯿⌀-⏿←-⇿■-◿⤀-⥿〰〽㊗㊙©®‼⁉™ℹ]"
EMOJI = re.compile("[\U0001f1e6-\U0001f1ff]{2}|[0-9#*]️?⃣|" + f"{_PIC}{_MOD}[\U000e0020-\U000e007f]*(?:‍{_PIC}{_MOD})*")


def units(text):
    """Discord counts a status in utf-16 units, so most emojis are two."""
    return len(text.encode("utf-16-le")) // 2


def fit(text):
    if units(text) <= STATUS_MAX:
        return text
    while units(text) > STATUS_MAX:
        text = text[:-1]
    return (text.rsplit(" ", 1)[0] if " " in text else text).rstrip(" ,.-")


def tidy(data):
    """(text, emoji) from what the model wrote, or None if it isn't usable as a public status."""
    data = data or {}
    found = EMOJI.search(str(data.get("emoji") or ""))
    if found is None:
        return None
    emoji = found.group(0)
    text = re.sub(r"\s+", " ", str(data.get("status") or "")).replace(emoji, "").strip().strip('"“”').strip()
    if not text or NOT_FOR_A_STATUS.search(text) or explicit(text) or tone_problem(text) or tone_problem(emoji):
        return None
    return fit(text), emoji


class CustomStatus(Component):
    def __init__(self, app):
        super().__init__(app)
        self.file = JsonFile(app.cfg.paths.data_file("status.json"))
        self.data = {}

    def load(self):
        self.data = self.file.load()

    @property
    def every(self):
        return max(60, self.cfg.STATUS_AUTO_MIN * 60)

    @property
    def current(self):
        if not self.cfg.STATUS_AUTO or not self.data.get("text"):
            return None
        return self.data["text"], self.data.get("emoji") or None

    def activity(self):
        current = self.current
        return discord.CustomActivity(current[0], emoji=current[1]) if current else None

    def clear(self):
        """Gone until her next new one."""
        self.data.update(text="", emoji="")
        self.file.save(self.data)

    def due_in(self):
        return max(0.0, self.data.get("at", 0) + self.every - time.time())

    async def run(self):
        if not self.cfg.STATUS_AUTO:
            return
        await asyncio.sleep(max(random.uniform(*START_DELAY), self.due_in()))
        while True:
            await asyncio.sleep(self.every if await self.refresh() else RETRY_SEC)

    async def refresh(self):
        """Her model writes a new status and it goes up. False if it didn't work, and the old one stays."""
        try:
            out = await self.llm.helper(self._prompt(), temperature=TEMPERATURE, n_predict=TOKENS, json_schema=SCHEMA)
        except Exception as e:
            log.warning("couldn't write a new status: %s", e)
            return False
        made, recent = tidy(parse_json(out)), list(self.data.get("recent") or [])
        if made is None or made[0].lower() in {r.lower() for r in recent}:
            log.info("her model's status wasn't usable: %r", out)
            return False
        text, emoji = made
        self.data = {"text": text, "emoji": emoji, "at": time.time(), "recent": [text, *recent][:RECENT_KEPT]}
        self.file.save(self.data)
        log.info("new status: %s %s", emoji, text)
        try:
            await self.app.profiles.apply()
        except Exception as e:
            log.warning("couldn't put the new status up: %s", e)
        return True

    def _prompt(self):
        persona = "\n\n".join(p for p in (tame(self.cfg.PERSONA), self.cfg.get("STYLE_NOTE"), EVERYONE_SEES) if p)
        spell = self.app.routine.spell()
        recent = self.data.get("recent") or []
        about = [
            time_phrase(self.app.clock.now()),
            f"Right now you're {spell.what}." if spell is not None else "",
            self.app.feelings.mood_note(),
            f"Your last statuses, don't repeat them or sound like them: {' | '.join(recent)}" if recent else "",
            'Write it as {"status": "...", "emoji": "..."}.',
        ]
        return self.llm.fmt.instruct(f"{persona}\n\n{INSTRUCTIONS}", "\n".join(a for a in about if a))
