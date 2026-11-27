import asyncio
import random
import shutil
import subprocess
from collections import defaultdict

import discord

from mitski.core import logs

log = logs.get("voice")


def probe_duration(path):
    probe = shutil.which("ffprobe")
    if probe:
        try:
            out = subprocess.run(
                [probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                capture_output=True,
                text=True,
                timeout=15,
            ).stdout.strip()
            return float(out) if out else None
        except (ValueError, OSError, subprocess.SubprocessError):
            pass
    try:
        from mutagen.mp3 import MP3

        return float(MP3(str(path)).info.length)
    except Exception:
        return None


class TypingSounds:
    def __init__(self, path, volume):
        self.path = path
        self.volume = volume
        self.ffmpeg = shutil.which("ffmpeg")
        self.duration = None
        self.counts = defaultdict(int)
        self.vc = None
        self.guild = None
        self.everywhere = False
        self._generation = 0
        self._pending_stop = None
        self.held = False

    def load(self):
        if self.path.exists():
            self.duration = probe_duration(self.path)

    def status(self):
        if not self.path.exists():
            return f"no typing sounds ({self.path} not found)"
        if not self.ffmpeg:
            return "no typing sounds (ffmpeg isn't on PATH)"
        return f"typing sounds from {self.path.name}" + (f" ({self.duration:.0f}s)" if self.duration else "")

    def attach(self, vc, place, everywhere=False):
        self.vc, self.guild, self.everywhere = vc, place, everywhere

    def detach(self):
        self.held = False
        self.stop()
        self.vc = self.guild = None
        self.everywhere = False

    def typing_here(self, place):
        return self.counts.get(place, 0) > 0

    def heard_typing(self):

        return sum(self.counts.values()) if self.everywhere else self.counts.get(self.guild, 0)

    def _hears(self, place):
        return self.guild is not None and (self.everywhere or self.guild == place)

    def started(self, place):
        self.counts[place] += 1
        if self._pending_stop is not None:
            self._pending_stop.cancel()
            self._pending_stop = None
            if self.held or (self.vc is not None and self.vc.is_playing()):
                return
        if self._hears(place) and self.heard_typing() == 1:
            self._play()

    def stopped(self, place):
        self.counts[place] = max(0, self.counts[place] - 1)
        if not self.counts[place]:
            self.counts.pop(place, None)
        if self._hears(place) and not self.heard_typing():
            self._pending_stop = asyncio.get_running_loop().call_later(0.3, self.stop)

    def stop(self):
        self._pending_stop = None
        self._generation += 1
        if not self.held and self.vc is not None and self.vc.is_playing():
            self.vc.stop()

    def hold(self):
        self.stop()
        self.held = True

    def release(self):
        self.held = False
        if self.guild is not None and self.heard_typing():
            self._play()

    def _play(self):
        vc = self.vc
        if self.held or vc is None or not self.ffmpeg or not self.path.exists() or not vc.is_connected():
            return
        self._generation += 1
        generation = self._generation
        if vc.is_playing():
            vc.stop()
        start = random.uniform(0, max(0.0, self.duration - 3)) if self.duration else 0.0
        try:
            source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(
                    str(self.path), before_options=f"-ss {start:.2f}", options="-vn -af afade=t=in:d=0.15"
                ),
                volume=self.volume,
            )
            loop = asyncio.get_running_loop()
            vc.play(source, after=lambda err: loop.call_soon_threadsafe(self._ended, generation, err))
        except Exception:
            log.warning("couldn't play %s", self.path.name, exc_info=True)

    def _ended(self, generation, err):
        if err:
            log.info("playback error: %r", err)
        if generation == self._generation and self.guild is not None and self.heard_typing() and not err:
            self._play()


class Typing:
    def __init__(self, sounds, channel):
        self.sounds = sounds
        self.channel = channel
        guild = getattr(channel, "guild", None)
        self.place = getattr(guild, "id", None) if guild is not None else getattr(channel, "id", None)
        self.inner = None

    async def __aenter__(self):
        self.inner = self.channel.typing()
        await self.inner.__aenter__()
        if self.place is not None:
            self.sounds.started(self.place)
        return self

    async def __aexit__(self, *exc):
        if self.place is not None:
            self.sounds.stopped(self.place)
        return await self.inner.__aexit__(*exc)
