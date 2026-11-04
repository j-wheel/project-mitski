import json
import textwrap

from mitski.config.schema import SECRETS, SECTIONS

WIDTH = 120


def value(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(value(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)


def option_lines(key, default, doc):
    head = f"{key}: {value(default)}"
    if not doc:
        return [head]
    room = max(40, WIDTH - len(head) - 3)
    pieces = textwrap.wrap(doc, room) if len(head) < WIDTH - 40 else textwrap.wrap(doc, WIDTH - 2)
    if len(head) >= WIDTH - 40:
        return [head] + [f"# {p}" for p in pieces]
    pad = " " * len(head)
    return [f"{head} # {pieces[0]}"] + [f"{pad} # {p}" for p in pieces[1:]]


def render_config():
    out = []
    for section in SECTIONS:
        if out:
            out.append("")
        out += [f"# {line}" for line in textwrap.wrap(section.title, WIDTH - 2)]
        for o in section.options:
            out += option_lines(o.key, o.default, o.doc)
    return "\n".join(out) + "\n"


def render_keys(values=None):
    values = values or {}
    out = ["# everything secret lives here, not in mitski.yaml. keep this file out of git"]
    for o in SECRETS:
        out += option_lines(o.key, values.get(o.key, o.default), o.doc)
    return "\n".join(out) + "\n"
