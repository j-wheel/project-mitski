"""Small, human typos: a neighbouring key, two letters swapped, a missed or a doubled letter. At most one per
message, never in the first letter of a word, short words, CAPS, links, mentions, emojis or stickers."""

import re

from mitski.chat.style import PROTECT

ROWS = ("qwertyuiop", "asdfghjkl", "zxcvbnm")
WORD = re.compile(r"(?<![\w'@#:])[A-Za-z]{4,}(?![\w'])")
KINDS = ("neighbour", "swap", "drop", "double")
WEIGHTS = (35, 30, 25, 10)


def _neighbours():
    near = {}
    for r, row in enumerate(ROWS):
        for i, ch in enumerate(row):
            keys = set()
            for other in ROWS[max(0, r - 1) : r + 2]:
                keys.update(other[max(0, i - 1) : i + 2])
            keys.discard(ch)
            near[ch] = "".join(sorted(keys))
    return near


NEIGHBOURS = _neighbours()


def chance(line, base):
    """Longer messages are a bit more likely to have one, a two word message hardly ever does."""
    words = len(line.split())
    return max(0.0, min(1.0, base * min(max(words / 6, 0.3), 2.5)))


def mistype(word, rng):
    """One small slip in a word, or None if none of the tries made a believable one."""
    for _ in range(8):
        kind = rng.choices(KINDS, WEIGHTS)[0]
        i = rng.randrange(1, len(word))
        if kind == "neighbour":
            near = NEIGHBOURS.get(word[i].lower())
            if not near:
                continue
            key = rng.choice(near)
            out = word[:i] + (key.upper() if word[i].isupper() else key) + word[i + 1 :]
        elif kind == "swap":
            i = rng.randrange(1, len(word) - 1)
            if word[i].lower() == word[i + 1].lower():
                continue
            out = word[:i] + word[i + 1] + word[i] + word[i + 2 :]
        elif kind == "drop":
            doubled = [k for k in range(1, len(word)) if word[k].lower() == word[k - 1].lower()]
            if doubled and rng.random() < 0.6:
                i = rng.choice(doubled)
            out = word[:i] + word[i + 1 :]
        else:
            if i >= len(word) - 1 or word[i].lower() in (word[i - 1].lower(), word[i + 1].lower()):
                continue
            out = word[:i] + word[i] + word[i:]
        if out.lower() != word.lower():
            return out
    return None


def add_typo(line, rng):
    """Puts one typo in a line. Returns (line, (typo, word)), or (line, None) when there's no good word for it."""
    held = [(m.start(), m.end()) for m in PROTECT.finditer(line)]
    words = [
        m
        for m in WORD.finditer(line)
        if not m.group().isupper() and not any(a < m.end() and m.start() < b for a, b in held)
    ]
    if not words:
        return line, None
    m = rng.choice(words)
    typo = mistype(m.group(), rng)
    if typo is None:
        return line, None
    return line[: m.start()] + typo + line[m.end() :], (typo, m.group())


def star(word, rng):
    """The quick follow-up people send to correct themselves: mostly "*word", sometimes "word*"."""
    return f"{word}*" if rng.random() < 0.15 else f"*{word}"


def fix(content, typo, word):
    """The message with the typo put right, or None if it isn't in there any more."""
    fixed, n = re.subn(rf"(?<![\w']){re.escape(typo)}(?![\w'])", word, content or "", count=1)
    return fixed if n else None
