import re
from functools import cache
from pathlib import Path

from mitski.paths import PROJECT, Paths

BUNDLED = PROJECT / "prompts"
SLOT = re.compile(r"\{\{([A-Za-z_]\w*)\}\}|\{([A-Za-z_]\w*)\}")


class TextError(KeyError):
    pass


def _read(folder):
    import yaml

    out = {}
    for file in sorted(Path(folder).glob("*.yaml")):
        data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise TextError(f"{file} should be a list of name: text entries")
        out[file.stem] = data
    return out


def _merge(base, extra):
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


@cache
def folder():
    configured = Paths.discover(create=False).get("prompts")
    return configured if configured is not None else BUNDLED


@cache
def _all():
    texts = _read(BUNDLED)
    mine = folder()
    if mine.resolve() != BUNDLED.resolve() and mine.is_dir():
        _merge(texts, _read(mine))
    return texts


def reload():
    folder.cache_clear()
    _all.cache_clear()


def wording(key):
    node = _all()
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            raise TextError(f"no text {key!r} in {folder()} (or the bundled prompts/)")
        node = node[part]
    return node


def fill(template, **values):
    def put(m):
        if m.group(1):
            return "{" + m.group(1) + "}"
        name = m.group(2)
        if name not in values:
            raise TextError(f"the text needs {{{name}}}, which isn't given here: {template[:80]!r}")
        return str(values[name])

    return SLOT.sub(put, template)


def fill_all(node, **values):
    if isinstance(node, str):
        return fill(node, **values)
    if isinstance(node, list):
        return [fill_all(v, **values) for v in node]
    if isinstance(node, dict):
        return {k: fill_all(v, **values) for k, v in node.items()}
    return node


def say(key, **values):
    return fill(wording(key), **values)


def slots(template):
    return {m.group(2) for m in SLOT.finditer(template) if m.group(2)}
