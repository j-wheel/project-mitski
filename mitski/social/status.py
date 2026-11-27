import asyncio
import random
import re
import time

import discord

from mitski.chat.policy import SAFE_REMINDER, explicit, tame, tone_problem
from mitski.core import logs
from mitski.core.component import Component
from mitski.core.storage import JsonFile
from mitski.core.texts import say, wording
from mitski.llm.helper import parse_json

log = logs.get("status")

STATUS_MAX = 128
START_DELAY = (60, 180)
RETRY_SEC = 600
RECENT_KEPT = 12
ANGLES_KEPT = 10
TRIES = 3
TOKENS = 120
TEMPERATURE = 1.0
DAY_CHANCE = 0.3
GAME_ANGLES = set(wording("status.game_angles"))
ANGLES = [*wording("status.angles"), *wording("status.game_angles")]
DAY_ANGLE = wording("status.day_angle")
SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "minLength": 1, "maxLength": STATUS_MAX},
        "emoji": {"type": "string", "minLength": 1, "maxLength": 16},
    },
    "required": ["status", "emoji"],
    "additionalProperties": False,
}
INSTRUCTIONS = say("status.instructions", max=STATUS_MAX)
EVERYONE_SEES = say("status.everyone_sees", safe_reminder=SAFE_REMINDER)
NOT_FOR_A_STATUS = re.compile(r"@|https?://|discord\.gg/", re.I)
GLUED = re.compile(r"\s[+&|]\s|\s-\s|\s/\s")
CLOCK = re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b|\b\d{1,2}:\d{2}\b", re.I)
WORDS = re.compile(r"[a-z0-9']+")
_MOD = "[\U0001f3fb-\U0001f3ff]?️?"
_PIC = "[\U0001f000-\U0001faff☀-➿⬀-⯿⌀-⏿←-⇿■-◿⤀-⥿〰〽㊗㊙©®‼⁉™ℹ]"
EMOJI = re.compile("[\U0001f1e6-\U0001f1ff]{2}|[0-9#*]️?⃣|" + f"{_PIC}{_MOD}[\U000e0020-\U000e007f]*(?:‍{_PIC}{_MOD})*")


def units(text):
    return len(text.encode("utf-16-le")) // 2


def fit(text):
    if units(text) <= STATUS_MAX:
        return text
    while units(text) > STATUS_MAX:
        text = text[:-1]
    return (text.rsplit(" ", 1)[0] if " " in text else text).rstrip(" ,.-")


def tidy(data):
    data = data or {}
    found = EMOJI.search(str(data.get("emoji") or ""))
    if found is None:
        return None
    emoji = found.group(0)
    text = re.sub(r"\s+", " ", str(data.get("status") or "")).replace(emoji, "").strip().strip('"“”').strip()
    if not text or NOT_FOR_A_STATUS.search(text) or explicit(text) or tone_problem(text) or tone_problem(emoji):
        return None
    return fit(text), emoji


def phrases(text, n=3):
    words = WORDS.findall(text.lower())
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def stale(text, recent, names=()):
    if GLUED.search(text):
        return "two things glued together"
    if CLOCK.search(text):
        return "a clock time"
    if text.lower() in {r.lower() for r in recent}:
        return "the same as before"
    used = set().union(*(phrases(r) for r in recent)) if recent else set()
    if phrases(text) & used:
        return "a phrase she's used before"
    words = set(WORDS.findall(text.lower()))
    named = next((n for n in names if n in words), None)
    if named:
        return f"names {named}"
    return None


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
        recent = list(self.data.get("recent") or [])
        angles = list(self.data.get("angles") or [])
        names = self._names()
        for _ in range(TRIES):
            angle = self._angle(angles)
            try:
                out = await self.llm.helper(
                    self._prompt(angle), temperature=TEMPERATURE, n_predict=TOKENS, json_schema=SCHEMA
                )
            except Exception as e:
                log.warning("couldn't write a new status: %s", e)
                return False
            made = tidy(parse_json(out))
            why = "not usable" if made is None else stale(made[0], recent, names)
            if why is None:
                break
            log.info("her model's status was %s: %r", why, out)
            angles = [angle, *angles][:ANGLES_KEPT]
        else:
            return False
        text, emoji = made
        self.data = {
            "text": text,
            "emoji": emoji,
            "at": time.time(),
            "recent": [text, *recent][:RECENT_KEPT],
            "angles": [angle, *angles][:ANGLES_KEPT],
        }
        self.file.save(self.data)
        log.info("new status: %s %s", emoji, text)
        try:
            await self.app.profiles.apply()
        except Exception as e:
            log.warning("couldn't put the new status up: %s", e)
        return True

    def _names(self):
        names = set(self.messages.speaker_names())
        return {n for n in names if len(n) >= 3 and " " not in n}

    def _angle(self, avoid):
        spell = self.app.routine.spell()
        if spell is not None and DAY_ANGLE not in avoid and random.random() < DAY_CHANCE:
            return DAY_ANGLE
        return random.choice([a for a in ANGLES if a not in avoid] or ANGLES)

    def _prompt(self, angle):
        persona = "\n\n".join(p for p in (tame(self.cfg.PERSONA), self.cfg.get("STYLE_NOTE"), EVERYONE_SEES) if p)
        spell = self.app.routine.spell()
        background = [f"it's {self.app.clock.now():%A}"]
        if angle == DAY_ANGLE and spell is not None:
            background.append(say("status.background_doing", doing=spell.what))
        if angle in GAME_ANGLES:
            playing = self.app.routine.game_now()
            if playing:
                background.append(say("status.background_playing", game=playing))
            elif self.cfg.ROUTINE_GAMES:
                some = random.sample(list(self.cfg.ROUTINE_GAMES), min(4, len(self.cfg.ROUTINE_GAMES)))
                background.append((wording("status.background_games") + " ") + ", ".join(some))
        about = [
            say("status.make_it", angle=angle),
            say("status.only_context", background=", ".join(background)),
            wording("status.answer_as"),
        ]
        return self.llm.fmt.instruct(f"{persona}\n\n{INSTRUCTIONS}", "\n".join(about))
