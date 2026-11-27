import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
FILE = "paths.yaml"

PLACES = (
    ("the bot", None),
    ("data", "data", "memory.db, mood, routine, caches, exports and training data"),
    ("sounds", "mp3", "keyboard sounds for vc (VOICE_ASMR_FILE is looked up in here)"),
    ("prompts", "prompts", "everything she's told: prompts, notes and instructions. a copy elsewhere overrides them"),
    ("llama-server (launch scripts can read these with: python mitski/paths.py <name>)", None),
    ("llama_server", "llama-server", "the llama-server executable, a bare name is looked up on PATH"),
    ("llm_model", "models/RVN-Q4_K_M-multilingual.gguf", "her model"),
    ("llm_mmproj", "models/mmproj-F16.gguf", "its vision projector, so she can see images"),
    ("llm_lora", "out_mitski2/mitski-lora-f16.gguf", "her lora, left out of the launch if the file isn't there"),
    ("embed_model", "models/Qwen3-Embedding-0.6B-Q8_0.gguf", "embedding model for memory search"),
    ("her voice (tools/voice_server.py)", None),
    ("applio", "Applio", "the Applio folder, its env/python.exe runs the voice server"),
    ("voice_model", "vmodel/voice.pth", "rvc model, .safetensors or applio .pth"),
    ("voice_index", "vmodel/voice.index", "its .index, empty for none"),
    ("training", None),
    ("lora_out", "out_mitski2", "where training/train_qwen.py saves the lora"),
    ("llama_cpp_repo", "llama.cpp", "a llama.cpp checkout, for converting the lora to gguf"),
)
DEFAULTS = {p[0]: p[1] for p in PLACES if p[1] is not None}
COMMANDS = {"llama_server"}


def render():
    out = [
        "# where things are on this pc. relative paths are from the project folder, ~ is your home folder,",
        "# forward slashes work on windows too. not in git",
    ]
    for place in PLACES:
        if place[1] is None:
            out += ["", f"# {place[0]}"]
            continue
        name, default, doc = place
        out.append(f'{name}: "{default}"  # {doc}')
    return "\n".join(out) + "\n"


def read(path):
    if not path.exists():
        return {}
    import yaml

    values = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(values, dict):
        raise SystemExit(f"{path} should be a list of name: path lines")
    unknown = sorted(set(values) - set(DEFAULTS))
    if unknown:
        print(f"unknown names in {path.name} (typos?): {', '.join(unknown)}", file=sys.stderr)
    return {k: "" if v is None else str(v) for k, v in values.items() if k in DEFAULTS}


@dataclass(frozen=True)
class Paths:
    root: Path
    places: dict = field(default_factory=dict, compare=False)

    @classmethod
    def discover(cls, create=True):
        home = os.environ.get("MITSKI_HOME")
        root = Path(home).resolve() if home else PROJECT
        file = root / "config" / FILE
        if create and not file.exists():
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(render(), encoding="utf-8")
        return cls(root, read(file))

    def get(self, name):
        if name not in DEFAULTS:
            raise KeyError(f"no path called {name!r} in {FILE}")
        raw = self.places.get(name, DEFAULTS[name])
        if not raw.strip():
            return None
        raw = raw.strip()
        if name in COMMANDS and not any(c in raw for c in "/\\~"):
            found = shutil.which(raw)
            if found:
                return Path(found)
        path = Path(os.path.expandvars(os.path.expanduser(raw)))
        return path if path.is_absolute() else self.root / path

    @property
    def config_dir(self):
        return self.root / "config"

    @property
    def config(self):
        return self.config_dir / "mitski.yaml"

    @property
    def keys(self):
        return self.config_dir / "keys.yaml"

    @property
    def paths_file(self):
        return self.config_dir / FILE

    @property
    def data(self):
        return self.get("data")

    @property
    def sounds(self):
        return self.get("sounds")

    def data_file(self, name):
        return self.data / name


def main(argv):
    paths = Paths.discover()
    if not argv or argv[0] in ("-h", "--help"):
        print(f"usage: python -m mitski.paths <name>   (names: {', '.join(DEFAULTS)})")
        print(f"reads {paths.paths_file}")
        return 0 if argv else 2
    try:
        path = paths.get(argv[0])
    except KeyError as e:
        print(e.args[0], file=sys.stderr)
        return 2
    sys.stdout.buffer.write(((path.as_posix() if path is not None else "") + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
