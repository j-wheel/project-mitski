import asyncio
import base64
import io
import shutil
import tempfile
from pathlib import Path

try:
    from PIL import Image, ImageFile

    ImageFile.LOAD_TRUNCATED_IMAGES = True
except ImportError:
    Image = None

GRID_HEIGHT = 360
GRID_GAP = 8
VIDEO_SPOTS = (0.05, 0.35, 0.65, 0.92)


def looks_like_video(data):
    return data[:4] == b"\x1aE\xdf\xa3" or data[4:8] == b"ftyp"


def flatten(im):
    im = im.convert("RGBA")
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    bg.alpha_composite(im)
    return bg.convert("RGB")


def spread(count, total):
    if count <= 1 or total <= 1:
        return [0]
    return sorted({round(i * (total - 1) / (count - 1)) for i in range(count)})


class FrameGrabber:
    def __init__(self, frames, max_side):
        self.frames = max(1, min(6, frames))
        self.max_side = max_side
        self.ffmpeg = shutil.which("ffmpeg")
        self.ffprobe = shutil.which("ffprobe")

    @property
    def available(self):
        return Image is not None

    async def grab(self, kind, data):
        if kind == "video" or looks_like_video(data):
            return await self._video(data)
        return await asyncio.to_thread(self._image, data)

    async def picture(self, kind, data):
        frames = await self.grab(kind, data) if data else []
        return (await asyncio.to_thread(self.grid, frames), len(frames)) if frames else (None, 0)

    def _image(self, data):
        im = Image.open(io.BytesIO(data))
        total = getattr(im, "n_frames", 1) or 1
        if total <= 1:
            return [flatten(im)]
        frames = []
        for i in spread(min(self.frames, total), total):
            try:
                im.seek(i)
                frames.append(flatten(im))
            except (EOFError, OSError, ValueError):
                break
        if not frames:
            im.seek(0)
            frames.append(flatten(im))
        return frames

    async def _run(self, *args, timeout, capture=False):
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE if capture else asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        return (out or b"").decode().strip()

    async def _duration(self, path):
        if not self.ffprobe:
            return 0.0
        out = await self._run(
            self.ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
            timeout=15,
            capture=True,
        )
        try:
            return float(out or 0)
        except ValueError:
            return 0.0

    async def _video(self, data):
        if not self.ffmpeg:
            return []
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in"
            src.write_bytes(data)
            duration = await self._duration(src)
            spots = [duration * f for f in VIDEO_SPOTS][: self.frames] if duration > 0.5 else [0]
            frames = []
            for i, t in enumerate(spots):
                dst = Path(tmp) / f"f{i}.png"
                await self._run(
                    self.ffmpeg,
                    "-v",
                    "error",
                    "-ss",
                    f"{t:.2f}",
                    "-i",
                    str(src),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=640:-2",
                    "-y",
                    str(dst),
                    timeout=30,
                )
                if dst.exists():
                    with Image.open(dst) as im:
                        frames.append(im.convert("RGB"))
            return frames

    def grid(self, frames):
        img = frames[0] if len(frames) == 1 else self._tile(frames)
        img = img.copy()
        img.thumbnail((self.max_side, self.max_side))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode()

    @staticmethod
    def _tile(frames):
        h = GRID_HEIGHT
        row = [f.resize((max(1, round(f.width * h / f.height)), h)) for f in frames]
        cols = 2 if len(row) == 4 else len(row)
        rows = [row[i : i + cols] for i in range(0, len(row), cols)]
        width = max(sum(f.width for f in r) + GRID_GAP * (len(r) - 1) for r in rows)
        img = Image.new("RGB", (width, h * len(rows) + GRID_GAP * (len(rows) - 1)), (30, 30, 30))
        y = 0
        for r in rows:
            x = 0
            for f in r:
                img.paste(f, (x, y))
                x += f.width + GRID_GAP
            y += h + GRID_GAP
        return img
