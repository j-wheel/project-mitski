import asyncio
import io
import random
import re
import time
from collections import deque

import aiohttp
import discord

from mitski.chat import guard
from mitski.chat.messages import short_name
from mitski.core import logs
from mitski.core.clock import time_phrase
from mitski.core.component import Component
from mitski.core.text import cut
from mitski.core.texts import fill, wording
from mitski.llm.client import ModelUnavailable

log = logs.get("talk")

FRAME_SEC = 0.02
END_SILENCE_SEC = 0.8
SHORTEST_SEC = 0.4
LONGEST_SEC = 20.0
SPEECH_RMS = 350
TRANSCRIPT_KEPT = 24
RECENT_SPEAKER_SEC = 25
ECHO_AFTER_SEC = 0.6
TIMEOUT = aiohttp.ClientTimeout(total=60)
NOT_SPEECH = re.compile(
    r"^\W*(?:thank you\W*|thanks for watching\W*|you|bye\W*|\[.*\]|\(.*\)|subtitles? by.*|music|♪+|\.+)\W*$", re.I
)
SPOKEN_JUNK = re.compile(r"<a?:\w+:\d+>|:\w{2,32}:|https?://\S+|<[@#][!&]?\d+>|[\U0001F000-\U0001FAFF☀-➿]")
VOICE_NOTE = wording("voice.talking_note")


def mono(pcm):
    import numpy as np

    samples = np.frombuffer(pcm, dtype=np.int16)
    if len(samples) % 2:
        return samples.tobytes()
    return samples.reshape(-1, 2).mean(axis=1).astype(np.int16).tobytes()


def loud(pcm):
    import numpy as np

    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    return bool(len(samples)) and float(np.sqrt(np.mean(samples**2))) >= SPEECH_RMS


SAID_AS = wording("voice.said_as")
SILENT = re.compile(r"\b(?:lol+|lmf?ao+|rofl|xd+|kkk+|ks(?:ks)+)\b|[,.]{2,}(?=\s|$)", re.I)
LAUGH = re.compile(r"\b(?:a?(?:ha){2,}h?|(?:he){2,}h?|(?:ah){2,}a?)\b", re.I)
SHORTHAND = re.compile(r"\b(" + "|".join(sorted(SAID_AS, key=len, reverse=True)) + r")\b", re.I)


def spoken(lines):
    text = " ".join(line.strip() for line in lines if line.strip())
    text = SPOKEN_JUNK.sub("", text)
    text = SILENT.sub("", text)
    text = LAUGH.sub("haha", text)
    text = SHORTHAND.sub(lambda m: SAID_AS[m.group(1).lower()], text)
    text = re.sub(r"(\w)\1{2,}", r"\1\1", text)
    text = re.sub(r"\s+([,.!?])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip(" ,")


class Utterance:
    def __init__(self):
        self.frames = []
        self.voiced = 0
        self.started = time.monotonic()
        self.last_voice = self.started

    @property
    def seconds(self):
        return self.voiced * FRAME_SEC


class VoiceTalk(Component):
    def __init__(self, app):
        super().__init__(app)
        self.vc = None
        self.loop = None
        self.listening = {}
        self.transcript = deque(maxlen=TRANSCRIPT_KEPT)
        self.speaking_until = 0.0
        self.replying = asyncio.Lock()
        self.waiting = None
        self.ticker = None
        self.server_ok = None

    @property
    def on(self):
        return self.cfg.VOICE_MODE == "voice"

    @property
    def live(self):
        return self.on and self.vc is not None

    @property
    def channel(self):
        return getattr(self.vc, "channel", None)

    @property
    def url(self):
        return str(self.cfg.VOICE_SERVER_URL or "").rstrip("/")

    def client_class(self):
        if not self.on:
            return discord.VoiceClient
        from mitski.voice.receive import ListeningVoiceClient

        return ListeningVoiceClient

    async def check(self):
        if not self.on:
            return
        try:
            async with self.app.http.get(f"{self.url}/health", timeout=aiohttp.ClientTimeout(total=5)) as r:
                info = await r.json(content_type=None) if r.status == 200 else {}
        except (aiohttp.ClientError, TimeoutError, ValueError):
            info = {}
        self.server_ok = bool(info.get("ok"))
        if self.server_ok:
            log.info("voice server: %s", ", ".join(f"{k} {v}" for k, v in info.items() if k != "ok"))
        else:
            log.warning(
                "VOICE_MODE is voice but the voice server at %s isn't answering, start tools/voice_server.py", self.url
            )

    def status(self):
        if not self.on:
            return "off"
        if self.server_ok is None:
            return f"on, voice server {self.url} not checked yet"
        return f"on, voice server {self.url}" if self.server_ok else f"on, but the voice server at {self.url} isn't up"

    def attach(self, vc):
        if not self.on or not hasattr(vc, "listen"):
            return
        self.vc = vc
        self.loop = asyncio.get_running_loop()
        self.listening.clear()
        self.transcript.clear()
        vc.listen(self._from_thread)
        if self.ticker is None or self.ticker.done():
            self.ticker = self.app.tasks.spawn(self._tick(), name="voice-ears")
        log.info("listening in %s", getattr(self.channel, "name", None) or "the call")

    def detach(self):
        if self.vc is not None and hasattr(self.vc, "stop_listening"):
            self.vc.stop_listening()
        self.vc = None
        self.waiting = None
        self.listening.clear()
        if self.ticker is not None:
            self.ticker.cancel()
            self.ticker = None

    def _from_thread(self, user_id, pcm):
        loop = self.loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._frame, user_id, pcm)

    def _frame(self, user_id, pcm):
        if user_id in self.cfg.ignored or (self.me and user_id == self.me.id):
            return
        heard = self.listening.get(user_id)
        voiced = loud(pcm)
        if heard is None:
            if not voiced:
                return
            heard = self.listening[user_id] = Utterance()
        heard.frames.append(pcm)
        if voiced:
            heard.voiced += 1
            heard.last_voice = time.monotonic()

    async def _tick(self):
        while self.vc is not None:
            await asyncio.sleep(0.15)
            self.flush(time.monotonic())

    def flush(self, now):
        for user_id, heard in list(self.listening.items()):
            if now - heard.last_voice < END_SILENCE_SEC and now - heard.started < LONGEST_SEC:
                continue
            self.listening.pop(user_id, None)
            if heard.seconds < SHORTEST_SEC:
                continue
            if heard.started < self.speaking_until and heard.seconds < 1.0:
                continue
            self.app.tasks.spawn(self._heard(user_id, heard), name=f"voice-heard-{user_id}")

    async def _heard(self, user_id, heard):
        audio = b"".join(mono(f) for f in heard.frames)
        text = await self._transcribe(audio)
        if not text or NOT_SPEECH.match(text) or guard.gibberish(text):
            return
        user = self._person(user_id)
        if user is None or getattr(user, "bot", False) or self.vc is None:
            return
        mine = [line for who, _, line, _ in self.transcript if who is None]
        if guard.quoted_from(text, mine):
            log.info("heard her own voice back through %s's mic, ignoring it", user)
            return
        name = self.messages.call(user)
        log.info("heard %s in vc: %s", user, text)
        self.transcript.append((user_id, name, text, time.time()))
        if self.cfg.MEMORY:
            self.memory.touch(user, text)
        if self._answers(text):
            self.waiting = user_id
            self.app.tasks.spawn(self._reply(), name="voice-reply")

    def _person(self, user_id):
        guild = getattr(self.channel, "guild", None)
        member = guild.get_member(user_id) if guild is not None else None
        return member or self.app.get_user(user_id)

    def others(self):
        channel = self.channel
        if channel is None:
            return []
        if getattr(channel, "guild", None) is not None:
            return self.app.voice.people(channel)
        return self.app.voice._call_people(getattr(channel, "call", None))

    def _names(self):
        out = {str(n).lower() for n in self.messages.own_names() if n}
        out |= {str(n).lower() for n in self.cfg.NAME_TRIGGERS or [] if n}
        return out

    def _answers(self, text):
        low = text.lower()
        if any(re.search(rf"\b{re.escape(n)}\b", low) for n in self._names()):
            return True
        if len(self.others()) <= 1:
            return True
        talked = [t for who, _, _, t in self.transcript if who is None]
        if talked and time.time() - talked[-1] < RECENT_SPEAKER_SEC:
            return random.random() < 0.75
        return random.random() < float(self.cfg.VOICE_SPEAK_CHIME)

    async def _reply(self):
        async with self.replying:
            if self.vc is None or self.waiting is None:
                return
            user = self._person(self.waiting)
            self.waiting = None
            if user is None:
                return
            try:
                lines = await self._write(user)
            except ModelUnavailable as e:
                log.info("couldn't answer in the call: %s", e)
                return
            text = spoken(lines)
            if not text:
                return
            if await self._say(text):
                self.transcript.append((None, short_name(self.me), text, time.time()))
                log.info("said in the call: %s", text)

    async def _write(self, user):
        turns, names = [], []
        last_line = ""
        for who, name, line, _ in self.transcript:
            role = "assistant" if who is None else "user"
            text = line if role == "assistant" else f"{name}: {line}"
            if role == "user":
                last_line = line
                if name not in names:
                    names.append(name)
            if turns and turns[-1][0] == role:
                turns[-1][1] += "\n" + text
            else:
                turns.append([role, text])
        if not turns or turns[-1][0] != "user":
            return []
        others = self.others()
        people = [p for p in (self._person(u) for u in others if u != user.id) if p is not None]
        persona = self.app.situation.persona(
            user, getattr(self.channel, "guild", None), channel=self.channel, people=people, about=False
        )
        notes = [fill(VOICE_NOTE, when=time_phrase(self.app.clock.now()), who=", ".join(names) or "them")]
        about = self.app.situation.about(user, channel=self.channel)
        if about:
            notes.append(about)
        seen = guard.read([last_line], self.messages.call(user), [], self.messages.own_names())
        notes += seen.notes
        mood = self.app.feelings.mood_note()
        if mood:
            notes.append(mood)
        if self.cfg.STYLE_NOTE:
            notes.append(self.cfg.STYLE_NOTE)
        note = "\n".join(notes)
        drafts = self.app.drafts
        for _ in range(2):
            out = await self.llm.generate(
                self.llm.prompt(turns, persona, note), cache_key=getattr(self.channel, "id", None)
            )
            lines = drafts.tidy(out, getattr(self.channel, "id", 0), names)
            problem = drafts.problem(lines, [], channel=self.channel, said=last_line, work=seen.work)
            if not problem:
                break
            log.info("her voice reply looked %r, trying again: %s", problem, " | ".join(lines))
            note += "\n" + wording("voice.fix_spoken")
        else:
            return []
        minors = self.app.ages.any_minor([user.id, *others])
        lines = self.app.policy.clean_lines(lines, self.channel, minors=minors)
        return [
            ln
            for ln in lines
            if not self.app.identity.wrong(ln)
            and not guard.gibberish(ln)
            and not guard.does_the_work([ln], asked=False)
        ]

    async def _transcribe(self, audio):
        try:
            async with self.app.http.post(
                f"{self.url}/hear", data=audio, headers={"Content-Type": "application/octet-stream"}, timeout=TIMEOUT
            ) as r:
                if r.status != 200:
                    log.info("the voice server couldn't hear that (%s)", r.status)
                    return ""
                return str((await r.json(content_type=None)).get("text") or "").strip()
        except (aiohttp.ClientError, TimeoutError) as e:
            log.info("voice server unreachable for hearing: %s", e)
            return ""

    async def _say(self, text):
        payload = {
            "text": cut(text, 600),
            "pitch": int(self.cfg.VOICE_SPEAK_PITCH),
            "voice": str(self.cfg.VOICE_SPEAK_VOICE),
            "speed": float(self.cfg.VOICE_SPEAK_SPEED),
        }
        pcm = await self._synth(payload)
        vc = self.vc
        if vc is None or not vc.is_connected() or not pcm:
            return False
        sounds = self.app.voice.sounds
        sounds.hold()
        done = asyncio.Event()
        loop = asyncio.get_running_loop()
        seconds = len(pcm) / (48000 * 2 * 2)
        self.speaking_until = time.monotonic() + seconds + ECHO_AFTER_SEC
        try:
            if vc.is_playing():
                vc.stop()
            vc.play(discord.PCMAudio(io.BytesIO(pcm)), after=lambda _err: loop.call_soon_threadsafe(done.set))
            await asyncio.wait_for(done.wait(), timeout=seconds + 10)
        except Exception:
            log.warning("couldn't play her voice", exc_info=True)
            return False
        finally:
            sounds.release()
        return True

    async def _synth(self, payload):
        try:
            async with self.app.http.post(f"{self.url}/speak", json=payload, timeout=TIMEOUT) as r:
                if r.status != 200:
                    log.info("the voice server couldn't say that (%s): %s", r.status, (await r.text())[:200])
                    return b""
                return await r.read()
        except (aiohttp.ClientError, TimeoutError) as e:
            log.info("voice server unreachable for speaking: %s", e)
            return b""

    def note(self):
        if not self.live:
            return ""
        heard = [f"{name}: {cut(line, 120)}" for who, name, line, _ in list(self.transcript)[-6:] if who is not None]
        if not heard:
            return ""
        return (wording("voice.heard_in_vc") + " ") + " | ".join(heard) + "."
