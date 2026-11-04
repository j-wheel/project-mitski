import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    root: Path

    @classmethod
    def discover(cls):
        home = os.environ.get("MITSKI_HOME")
        return cls(Path(home).resolve() if home else Path(__file__).resolve().parent.parent)

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
    def data(self):
        return self.root / "data"

    @property
    def sounds(self):
        return self.root / "mp3"

    def data_file(self, name):
        return self.data / name
