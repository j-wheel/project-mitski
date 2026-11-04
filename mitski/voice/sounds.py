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
        self._generation = 0
        self._pending_stop = None

    def load(self):
        if self.path.exists():
            self.duration = probe_duration(self.path)

    def status(self):
        if not self.path.exists():
            return f"no typing sounds ({self.path} not found)"
        if not self.ffmpeg:
            return "no typing sounds (ffmpeg isn't on PATH)"
        return f"typing sounds from {self.path.name}" + (f" ({self.duration:.0f}s)" if self.duration else "")

    def attach(self, vc, guild_id):
        self.vc, self.guild = vc, guild_id

    def detach(self):
        self.stop()
        self.vc = self.guild = None

    def typing_here(self, guild_id):
        return self.counts.get(guild_id, 0) > 0

    def started(self, guild_id):
        self.counts[guild_id] += 1
        if self._pending_stop is not None:
            self._pending_stop.cancel()
            self._pending_stop = None
            if self.vc is not None and self.vc.is_playing():
                return
        if self.counts[guild_id] == 1 and self.guild == guild_id:
            self._play()

    def stopped(self, guild_id):
        self.counts[guild_id] = max(0, self.counts[guild_id] - 1)
        if not self.counts[guild_id]:
            self.counts.pop(guild_id, None)
            if self.guild == guild_id:
                self._pending_stop = asyncio.get_running_loop().call_later(0.3, self.stop)

    def stop(self):
        self._pending_stop = None
        self._generation += 1
        if self.vc is not None and self.vc.is_playing():
            self.vc.stop()

    def _play(self):
        vc = self.vc
        if vc is None or not self.ffmpeg or not self.path.exists() or not vc.is_connected():
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
        if generation == self._generation and self.guild is not None and self.typing_here(self.guild) and not err:
            self._play()


class Typing:
    def __init__(self, sounds, channel):
        self.sounds = sounds
        self.channel = channel
        self.guild = getattr(getattr(channel, "guild", None), "id", None)
        self.inner = None

    async def __aenter__(self):
        self.inner = self.channel.typing()
        await self.inner.__aenter__()
        if self.guild is not None:
            self.sounds.started(self.guild)
        return self

    async def __aexit__(self, *exc):
        if self.guild is not None:
            self.sounds.stopped(self.guild)
        return await self.inner.__aexit__(*exc)
