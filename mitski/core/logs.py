import logging
import sys

ROOT = "mitski"
FORMAT = "%(asctime)s %(levelname)-7s %(name)-18s %(message)s"


class _Short(logging.Formatter):
    def format(self, record):
        if record.name == ROOT:
            record.name = "core"
        elif record.name.startswith(ROOT + "."):
            record.name = record.name.removeprefix(ROOT + ".")
        return super().format(record)


def setup(level="INFO"):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_Short(FORMAT, "%H:%M:%S"))
    root = logging.getLogger(ROOT)
    root.handlers[:] = [handler]
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    root.propagate = False
    library = logging.getLogger("discord")
    library.handlers[:] = [handler]
    library.setLevel(logging.INFO)
    library.propagate = False
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    return root


def get(name):
    return logging.getLogger(f"{ROOT}.{name}")
