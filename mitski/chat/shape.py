import random

from mitski.chat.patterns import STICKER_TAG

QUICK = "quick"
BLOCK = "block"
THREADED = "threaded"

TINY = 60
LONG_ANSWER = 200
LONG_ANSWERS = 300


def group_answers(lines, owners):
    """Lines that answer the same message go together, a line that answers nothing goes with its neighbours."""
    groups = {}
    waiting = []
    last = None
    for line, owner in zip(lines, owners, strict=True):
        if owner is None:
            if last is None:
                waiting.append(line)
            else:
                groups[last.id][1].append(line)
            continue
        group = groups.setdefault(owner.id, (owner, []))
        group[1].extend(waiting)
        group[1].append(line)
        waiting, last = [], owner
    return list(groups.values())


def threaded(groups, rng):
    """Each group replies to its own message. Extra lines go on the same message or follow it as plain ones."""
    parts, targets = [], []
    for msg, lines in groups:
        if len(lines) > 1 and rng.random() < 0.5:
            parts.append(lines)
            targets.append((msg, True))
        else:
            for i, line in enumerate(lines):
                parts.append([line])
                targets.append((msg, i == 0))
    return parts, targets


def pick(answers, *, serious=False, crowded=False, can_thread=False, longer=False, rng=None):
    """How a reply looks once it's written: a few quick messages, one longer message, or a reply to each question.

    The model can't choose this, it almost never saw a line break in training, so it's decided here from what a
    person would go by: how many things they're answering, how long it is, and how busy the chat is. A reply that
    was meant to be longer leans towards one proper message, the way people write when they're really explaining.
    """
    rng = rng or random
    lines = [ln for answer in answers for ln in answer]
    if len(lines) < 2 or any(STICKER_TAG.fullmatch(ln) for ln in lines):
        return QUICK
    chars = sum(map(len, lines))
    if len(answers) >= 2:
        weights = {QUICK: 4, BLOCK: 5, THREADED: 3}
        if chars > LONG_ANSWERS:
            weights[QUICK], weights[BLOCK] = 2, 8
    else:
        if chars < TINY:
            return QUICK
        weights = {QUICK: 9, BLOCK: 1, THREADED: 0}
        if chars > LONG_ANSWER:
            weights[BLOCK] += 3
    if crowded:
        weights[QUICK] = min(weights[QUICK], 1)
        weights[BLOCK] += 2
        weights[THREADED] += 2 if weights[THREADED] else 0
    if serious:
        weights[BLOCK] += 4
    if longer:
        weights[QUICK] = max(1, weights[QUICK] - 4)
        weights[BLOCK] += 6
    if not can_thread:
        weights[THREADED] = 0
    kinds = list(weights)
    return rng.choices(kinds, [weights[k] for k in kinds])[0]
