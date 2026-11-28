import argparse
import datetime as dt
import json
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mitski.brain import prompts  # noqa: E402
from mitski.chat import guard  # noqa: E402
from mitski.config import Settings  # noqa: E402
from mitski.core.clock import time_phrase  # noqa: E402
from mitski.core.texts import wording  # noqa: E402
from mitski.llm.prompt_format import Format  # noqa: E402
from mitski.paths import Paths  # noqa: E402

PORT = 5199
CHAT = [
    ["user", "rinmp3: did anyone see the new roblox update\nemidust: no what happened"],
    ["assistant", "THEY REMOVED THE OLD MAP\nim so mad"],
    ["user", "rinmp3: LMAO\nrinmp3: mitski ur so dramatic"],
    ["assistant", "im not dramatic im right 😡"],
    ["user", "emidust: wait what did u eat today mitski"],
    ["assistant", "chicken nuggets again\ndont judge me"],
    ["user", "rinmp3: we're playing valorant later u in?\nemidust: she's gonna say no lol"],
]


def parse():
    p = argparse.ArgumentParser(description="her speed with and without MTP speculative decoding, on her own setup")
    p.add_argument("--model", help="the -mtp gguf to test, default: llm_model in paths.yaml with -mtp added")
    p.add_argument("--n-max", default="2,3", help="draft lengths to try, comma separated")
    p.add_argument("--runs", type=int, default=5, help="requests per prompt kind")
    p.add_argument("--slots", type=int, default=3)
    p.add_argument("--ctx", type=int, default=36864)
    p.add_argument("--extra", default="", help="more llama-server flags for every run")
    return p.parse_args()


def setup():
    paths = Paths.discover()
    cfg = Settings.load(paths)
    return paths, cfg


def prompts_for(cfg):
    fmt = Format("qwen")
    persona = "\n\n".join([cfg.PERSONA, cfg.identity_note.replace("{name}", "mitski"), guard.STAY_A_PERSON])
    notes = "\n".join(
        [
            wording("chat.notes_header"),
            time_phrase(dt.datetime(2026, 11, 28, 21, 14)),
            "You're chatting in #main-chat with emidust, rinmp3.",
            cfg.STYLE_NOTE or "",
            wording("chat.notes_footer"),
        ]
    )
    reply = fmt.chat(persona, CHAT, notes)
    q = NS(
        her="mitski",
        name="rinmp3",
        parts=["we're playing valorant later u in?"],
        several=False,
        newest="we're playing valorant later u in?",
        about="",
        to_her="",
        remind=False,
        recent="\n".join(t for _, t in CHAT),
        knows="",
    )
    system, user, schema, budget = prompts.plan_request(q, prompts.available_tools(), dt.datetime(2026, 11, 28, 21, 14))
    helper = fmt.instruct(system, user)
    return {"reply": (reply, None, 120), "helper": (helper, schema, budget)}


def post(path, payload, timeout=300):
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}", json.dumps(payload).encode(), {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def healthy():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=3) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def vram():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        used, total = (int(x) for x in out.split(",")[:2])
        return f"{used}/{total} MiB"
    except Exception:
        return "?"


def run_config(name, args, server, base_args, cfg, kinds, runs, log_dir):
    log_file = log_dir / f"bench-{name}.log"
    with open(log_file, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [server, *base_args, *args], stdout=log, stderr=subprocess.STDOUT, cwd=Path(server).parent
        )
    try:
        start = time.monotonic()
        while not healthy():
            if proc.poll() is not None or time.monotonic() - start > 600:
                tail = log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
                return {"error": "llama-server didn't start:\n    " + "\n    ".join(tail)}
            time.sleep(2)
        out = {"vram": vram()}
        for kind, (prompt, schema, n_predict) in kinds.items():
            helper = kind == "helper"
            speeds, accepted, drafted = [], 0, 0
            for i in range(runs + 1):
                payload = {
                    "prompt": prompt,
                    "n_predict": n_predict,
                    "temperature": 0.2 if helper else cfg.TEMPERATURE,
                    "top_p": 0.8 if helper else cfg.TOP_P,
                    "top_k": 20 if helper else cfg.TOP_K,
                    "min_p": 0.0 if helper else cfg.MIN_P,
                    "presence_penalty": 0.0 if helper else cfg.PRESENCE_PENALTY,
                    "seed": 1000 + i,
                    "cache_prompt": True,
                    "id_slot": 2 if helper else 0,
                    "lora": [{"id": 0, "scale": 0.0 if helper else cfg.LORA_SCALE}],
                }
                if schema is not None:
                    payload["json_schema"] = schema
                try:
                    t = post("/completion", payload).get("timings") or {}
                except urllib.error.HTTPError as e:
                    if e.code == 400 and "lora" in payload:
                        payload.pop("lora")
                        t = post("/completion", payload).get("timings") or {}
                    else:
                        raise
                if i == 0:
                    continue
                speeds.append(float(t.get("predicted_per_second") or 0))
                drafted += int(t.get("draft_n") or 0)
                accepted += int(t.get("draft_n_accepted") or 0)
            out[kind] = {
                "tps": statistics.median(speeds),
                "accept": (accepted / drafted) if drafted else None,
            }
        return out
    finally:
        proc.terminate()
        try:
            proc.wait(30)
        except subprocess.TimeoutExpired:
            proc.kill()
        time.sleep(3)


def main():
    a = parse()
    paths, cfg = setup()
    server = str(paths.get("llama_server"))
    model = Path(a.model) if a.model else paths.get("llm_model")
    if not a.model and not model.stem.endswith("-mtp"):
        model = model.with_name(model.stem + "-mtp.gguf")
    if not model.exists():
        sys.exit(f"no {model}, download the -mtp twin of your model first (see the README)")
    if healthy():
        sys.exit(f"something already runs on port {PORT}")
    base = ["-m", str(model), "-ngl", "99", "-c", str(a.ctx), "-np", str(a.slots), "-fa", "on"]
    base += ["-ctk", "q8_0", "-ctv", "q8_0", "--jinja", "--host", "127.0.0.1", "--port", str(PORT)]
    mmproj, lora = paths.get("llm_mmproj"), paths.get("llm_lora")
    if mmproj and mmproj.exists():
        base += ["--mmproj", str(mmproj)]
    if lora and lora.exists():
        base += ["--lora", str(lora), "--lora-init-without-apply"]
    base += a.extra.split()
    kinds = prompts_for(cfg)
    configs = [("plain", [])] + [
        (f"mtp-{n}", ["--spec-type", "draft-mtp", "--spec-draft-n-max", n]) for n in a.n_max.split(",") if n
    ]
    print(f"model {model.name}, {a.slots} slots, {a.ctx} ctx, lora {'on' if lora and lora.exists() else 'off'}")
    print(f"{a.runs} requests per kind: her replies (lora {cfg.LORA_SCALE}, temp {cfg.TEMPERATURE}) and helper json")
    results = {}
    for name, args in configs:
        print(f"\n{name}: starting llama-server...", flush=True)
        results[name] = run_config(name, args, server, base, cfg, kinds, a.runs, paths.data)
        r = results[name]
        if "error" in r:
            print(f"  {r['error']}")
            continue
        for kind in kinds:
            acc = r[kind]["accept"]
            print(
                f"  {kind:6} {r[kind]['tps']:6.1f} tok/s" + (f", {acc:.0%} of drafted tokens accepted" if acc else "")
            )
        print(f"  vram {r['vram']}")
    plain = results.get("plain", {})
    if "error" not in plain:
        print("\nvs plain:")
        for name, r in results.items():
            if name == "plain" or "error" in r:
                continue
            bits = [f"{kind} {r[kind]['tps'] / plain[kind]['tps'] - 1:+.0%}" for kind in kinds if plain[kind]["tps"]]
            print(f"  {name}: " + ", ".join(bits))
    print(f"\nserver logs: {paths.data}/bench-*.log")


if __name__ == "__main__":
    main()
