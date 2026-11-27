import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mitski.paths import Paths  # noqa: E402

PATHS = Paths.discover()
OUT_SR = 48000
RVC_SR = 16000
TTS_SR = 24000
QUIET_RMS = 0.006


def parse():
    p = argparse.ArgumentParser(description="mitski's voice: kokoro tts -> rvc voice, and whisper to hear")
    p.add_argument("--applio", default=str(PATHS.get("applio") or ""), help="the Applio folder, default: paths.yaml")
    p.add_argument("--model", default=str(PATHS.get("voice_model") or ""), help="rvc model, default: paths.yaml")
    p.add_argument("--index", default=str(PATHS.get("voice_index") or ""), help="rvc .index, default: paths.yaml")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5113)
    p.add_argument("--pitch", type=int, default=0, help="default semitone shift when the bot doesn't send one")
    p.add_argument("--index-rate", type=float, default=0.6)
    p.add_argument("--protect", type=float, default=0.5)
    p.add_argument("--volume-envelope", type=float, default=1.0)
    p.add_argument("--f0", default="rmvpe", help="rmvpe, crepe, fcpe ...")
    p.add_argument("--voice", default="af_heart", help="default kokoro voice")
    p.add_argument("--lang", default="a", help="kokoro language: a american english, b british english")
    p.add_argument("--tts-device", default="cuda", help="cuda or cpu (kokoro is small, cpu works fine too)")
    p.add_argument("--stt-model", default="openai/whisper-small", help="e.g. openai/whisper-large-v3-turbo")
    p.add_argument("--stt-device", default="cuda")
    p.add_argument("--stt-language", default="", help="force a language like en or pt, empty to detect it")
    p.add_argument("--no-rvc", action="store_true", help="plain kokoro voice, skip the rvc model")
    args = p.parse_args()
    args.applio = str(Path(args.applio).expanduser().resolve())
    args.model = str(Path(args.model).expanduser().resolve())
    args.index = str(Path(args.index).expanduser().resolve()) if args.index else ""
    if not args.no_rvc and not Path(args.model).is_file():
        raise SystemExit(f"no rvc model at {args.model}, set voice_model in {PATHS.paths_file} or pass --model")
    if args.index and not Path(args.index).is_file():
        print(f"no index at {args.index}, going without one")
        args.index = ""
    return args


def resample(audio, src, dst):
    if src == dst:
        return audio
    import soxr

    return soxr.resample(audio, src, dst)


def to_pcm48_stereo(audio, sr):
    audio = resample(np.asarray(audio, dtype=np.float32), sr, OUT_SR)
    peak = float(np.abs(audio).max()) if len(audio) else 0.0
    if peak > 0.99:
        audio = audio / peak * 0.99
    pcm = (audio * 32767).astype(np.int16)
    return np.repeat(pcm[:, None], 2, axis=1).tobytes()


def applio_checkpoint(path):
    path = Path(path)
    if path.suffix.lower() != ".safetensors":
        return str(path)
    out = path.with_suffix(".applio.pth")
    if out.exists() and out.stat().st_mtime >= path.stat().st_mtime:
        return str(out)
    import torch
    from safetensors import safe_open
    from safetensors.torch import load_file

    with safe_open(str(path), "pt") as f:
        meta = f.metadata() or {}
    if "config" not in meta:
        raise SystemExit(f"{path.name} has no rvc config in its metadata, point --model at the applio .pth instead")
    cpt = {
        "weight": load_file(str(path)),
        "config": json.loads(meta["config"]),
        "f0": 1 if str(meta.get("f0", "True")).lower() in ("1", "true") else 0,
        "version": meta.get("version", "v2"),
        "sr": meta.get("sr", "40000"),
        "vocoder": meta.get("vocoder", "HiFi-GAN"),
        "embedder_model": meta.get("embedder_model", "contentvec"),
        "model_name": meta.get("model_name", path.stem),
    }
    torch.save(cpt, str(out))
    print(f"converted {path.name} to {out.name} for applio")
    return str(out)


class CachedIndex:
    def __init__(self, index):
        self.index = index
        self.ntotal = index.ntotal
        self.vectors = None

    def reconstruct_n(self, start, count):
        if self.vectors is None:
            self.vectors = self.index.reconstruct_n(start, count)
        return self.vectors

    def search(self, *args, **kwargs):
        return self.index.search(*args, **kwargs)


class CachedFaiss:
    def __init__(self, real):
        self.real = real
        self.indexes = {}

    def read_index(self, path):
        got = self.indexes.get(path)
        if got is None:
            got = self.indexes[path] = CachedIndex(self.real.read_index(path))
        return got

    def __getattr__(self, name):
        return getattr(self.real, name)


class Voice:
    def __init__(self, args):
        self.args = args
        self.lock = threading.Lock()
        self.rvc = None
        self.tts = {}
        self.stt = None
        self.model_name = Path(args.model).stem

    def load(self):
        if not self.args.no_rvc:
            self._load_rvc()
        self._load_tts(self.args.lang)
        self._load_stt()

    def _load_rvc(self):
        applio = Path(self.args.applio).resolve()
        if not (applio / "rvc" / "infer" / "infer.py").exists():
            raise SystemExit(
                f"{applio} doesn't look like the Applio folder, set applio in {PATHS.paths_file} or pass --applio"
            )
        checkpoint = applio_checkpoint(self.args.model)
        os.chdir(applio)
        sys.path.insert(0, str(applio))
        import rvc.infer.pipeline as rvc_pipeline
        from rvc.infer.infer import VoiceConverter

        rvc_pipeline.faiss = CachedFaiss(rvc_pipeline.faiss)
        vc = VoiceConverter()
        vc.get_vc(checkpoint, 0)
        vc.load_hubert("contentvec")
        vc.last_embedder_model = "contentvec"
        self.rvc = vc
        index = self.args.index if self.args.index and Path(self.args.index).exists() else ""
        self.index = str(Path(index).resolve()) if index else ""
        print(f"rvc: {Path(checkpoint).name} at {vc.tgt_sr} Hz on {vc.config.device}, index {index or 'none'}")

    def _load_tts(self, lang):
        if lang in self.tts:
            return self.tts[lang]
        try:
            from kokoro import KPipeline
        except ImportError:
            raise SystemExit(
                "kokoro isn't installed in this python, run: <applio>\\env\\python.exe -m pip install kokoro"
            ) from None
        self.tts[lang] = KPipeline(lang_code=lang, device=self.args.tts_device, repo_id="hexgrad/Kokoro-82M")
        print(f"tts: kokoro ({lang}) on {self.args.tts_device}")
        return self.tts[lang]

    def _load_stt(self):
        import torch
        from transformers import pipeline

        device = self.args.stt_device if torch.cuda.is_available() or self.args.stt_device == "cpu" else "cpu"
        dtype = torch.float16 if device.startswith("cuda") else torch.float32
        self.stt = pipeline("automatic-speech-recognition", model=self.args.stt_model, device=device, dtype=dtype)
        print(f"stt: {self.args.stt_model} on {device}")

    def speak(self, text, pitch=None, voice=None, speed=1.0):
        voice = voice or self.args.voice
        pipe = self._load_tts(
            voice[0] if voice[:1] in ("a", "b", "e", "f", "h", "i", "j", "p", "z") else self.args.lang
        )
        chunks = []
        with self.lock:
            for result in pipe(text, voice=voice, speed=float(speed or 1.0), split_pattern=r"\n+"):
                audio = result.audio if hasattr(result, "audio") else result[2]
                if audio is not None:
                    chunks.append(audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio))
            if not chunks:
                return b""
            audio = np.concatenate(chunks).astype(np.float32)
            if self.rvc is None:
                return to_pcm48_stereo(audio, TTS_SR)
            audio = resample(audio, TTS_SR, RVC_SR)
            peak = float(np.abs(audio).max()) / 0.95
            if peak > 1:
                audio = audio / peak
            vc = self.rvc
            out = vc.vc.pipeline(
                model=vc.hubert_model,
                net_g=vc.net_g,
                sid=0,
                audio=audio,
                pitch=self.args.pitch if pitch is None else int(pitch),
                f0_method=self.args.f0,
                file_index=self.index,
                index_rate=self.args.index_rate,
                pitch_guidance=vc.use_f0,
                volume_envelope=self.args.volume_envelope,
                version=vc.version,
                protect=self.args.protect,
                f0_autotune=False,
                f0_autotune_strength=1.0,
                proposed_pitch=False,
                proposed_pitch_threshold=155.0,
            )
        return to_pcm48_stereo(out, vc.tgt_sr)

    def hear(self, pcm, sr=OUT_SR):
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if len(audio) < sr * 0.3 or float(np.sqrt(np.mean(audio**2))) < QUIET_RMS:
            return ""
        audio = resample(audio, sr, 16000)
        kwargs = {"task": "transcribe"}
        if self.args.stt_language:
            kwargs["language"] = self.args.stt_language
        with self.lock:
            got = self.stt({"raw": audio, "sampling_rate": 16000}, generate_kwargs=kwargs)
        return str(got.get("text") or "").strip()


def app_for(voice):
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import Response
    from starlette.concurrency import run_in_threadpool

    app = FastAPI(title="mitski voice")

    @app.get("/health")
    def health():
        return {
            "ok": True,
            "voice": voice.model_name if voice.rvc is not None else "plain kokoro",
            "tts": voice.args.voice,
            "stt": voice.args.stt_model,
        }

    @app.post("/speak")
    async def speak(request: Request):
        body = await request.json()
        text = str(body.get("text") or "").strip()
        if not text:
            raise HTTPException(400, "no text")
        start = time.monotonic()
        pcm = await run_in_threadpool(voice.speak, text, body.get("pitch"), body.get("voice"), body.get("speed", 1.0))
        print(f"spoke {len(pcm) / (OUT_SR * 4):.1f}s in {time.monotonic() - start:.1f}s: {text[:80]}")
        return Response(pcm, media_type="application/octet-stream")

    @app.post("/hear")
    async def hear(request: Request):
        pcm = await request.body()
        sr = int(request.query_params.get("sr", OUT_SR))
        start = time.monotonic()
        text = await run_in_threadpool(voice.hear, pcm, sr)
        if text:
            print(f"heard {len(pcm) / (sr * 2):.1f}s in {time.monotonic() - start:.1f}s: {text[:80]}")
        return {"text": text}

    return app


def main():
    args = parse()
    voice = Voice(args)
    voice.load()
    start = time.monotonic()
    voice.speak("hey, just warming up.")
    print(f"warmed up in {time.monotonic() - start:.1f}s")
    import uvicorn

    print(f"mitski voice listening on http://{args.host}:{args.port}")
    uvicorn.run(app_for(voice), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
