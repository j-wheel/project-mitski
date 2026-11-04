import json
import os
from pathlib import Path

from mitski.core import logs

log = logs.get("storage")


def write_atomic(path, text, newline="\n"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(text.replace("\n", newline).encode("utf-8"))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_text(path):
    raw = Path(path).read_bytes().decode("utf-8")
    return raw.replace("\r\n", "\n"), "\r\n" if "\r\n" in raw else "\n"


class JsonFile:
    def __init__(self, path, default=None, indent=2):
        self.path = Path(path)
        self.default = default if default is not None else {}
        self.indent = indent

    def load(self):
        if not self.path.exists():
            return _fresh(self.default)
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            log.warning("couldn't read %s, starting from scratch", self.path.name, exc_info=True)
            return _fresh(self.default)

    def save(self, data):
        write_atomic(self.path, json.dumps(data, ensure_ascii=False, indent=self.indent))


def _fresh(default):
    return json.loads(json.dumps(default))
