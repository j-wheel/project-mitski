import random
import re


class Delivery:
    def __init__(self, kind="plain", msg=None, user=None, at_end=False, why="", reply_ping=None):
        self.kind, self.msg, self.user, self.at_end, self.why = kind, msg, user, at_end, why
        self.reply_ping = reply_ping

    @property
    def to_id(self):
        return getattr(self.user, "id", None)

    def describe(self, name_of):
        if self.user is None:
            return "to the chat"
        name = name_of(self.user)
        return {"reply": f"reply to {name}", "ping": f"@{name}"}.get(self.kind, f"to {name}") + (
            f", {self.why}" if self.why else ""
        )


def decide(
    addr,
    after,
    her_id,
    *,
    explicit=False,
    reply_back=0.7,
    casual_reply=0.3,
    ping_chance=0.25,
    can_ping=True,
    crowded=False,
    rng=None,
):
    rng = rng or random.Random()
    if addr is None:
        return Delivery("plain", why="")
    them = addr.author
    others = [a for a in after if a not in (her_id, them.id)]
    theirs = sum(1 for a in after if a == them.id)
    if not others and not crowded:
        if theirs >= 3:
            return Delivery("reply", addr, them, why="an older message of theirs")
        if rng.random() < (reply_back if explicit else casual_reply):
            return Delivery("reply", addr, them)
        return Delivery("plain", addr, them)
    content = getattr(addr, "content", "") or ""
    far = len(after) >= 8 and theirs == 0
    asked_long_ago = "?" in content and len(after) >= 6
    if can_ping and not asked_long_ago and rng.random() < min(1.0, ping_chance * (1.6 if far else 1.0)):
        return Delivery("ping", addr, them, at_end=rng.random() < 0.2, why=_why(others, crowded))
    return Delivery("reply", addr, them, why=_why(others, crowded))


def _why(others, crowded):
    if others:
        return f"{len(others)} message{'s' if len(others) != 1 else ''} since"
    return "talking with others too" if crowded else ""


def too_late(after, her_id, limit):
    return limit > 0 and sum(1 for a in after if a != her_id) >= limit


CHECK = {
    "type": "object",
    "properties": {
        "fits": {"type": "boolean"},
        "to": {"type": "integer", "minimum": 0, "maximum": 60},
        "mixed_up": {"type": "boolean"},
    },
    "required": ["fits", "to", "mixed_up"],
    "additionalProperties": False,
}


def check_request(her, numbered, draft, meant, meant_label):
    chat = "\n".join(f"[{i}] {label}: {text}" for i, (label, text) in enumerate(numbered, 1))
    who = meant_label.split(" (")[0]
    system = (
        "You check messages in a discord group chat before they're sent: does a reply fit the message it's "
        "meant for, and does it get the chat right? Answer with JSON: "
        '{"fits": true/false, "to": number, "mixed_up": true/false}.'
    )
    user = (
        f"The chat, oldest first:\n{chat}\n\n"
        f'{her} is replying to [{meant}] ({who}). Her reply:\n"{draft}"\n\n'
        f"fits: true if it works as {her}'s reply to [{meant}]: it answers it, reacts to it, jokes about it, or "
        f'just carries on her chat with {who}. Short or vague replies ("lol", "fr", "wait what", an '
        f'emoji) fit. Telling {who} ABOUT someone else or about what she said to someone else fits too ("i just '
        f'said that to tom", "he started it"): what counts is who she\'s talking TO, not who she mentions. '
        f"false ONLY if it clearly answers or reacts to a different message instead: it answers someone else's "
        f"question, it reacts to what someone else said instead of to [{meant}], or it talks to someone else by "
        f"name.\n"
        f"to: when fits is false, the number of the message it really answers, or 0 if it's a remark to the whole "
        f"chat. When fits is true, {meant}.\n"
        f"mixed_up: true only if her reply clearly gets the chat above wrong about who said or did what: it says "
        f'someone said something to her that she said herself (look at the lines marked "(her)"), or the other '
        f"way round, or it says something happened in the chat that didn't. Jokes, teasing, exaggerating and "
        f"things about her own life are fine (false)."
    )
    return system, user


def parse_check(out, count, meant):
    if not isinstance(out, dict) or not isinstance(out.get("fits"), bool):
        return None, None, False
    mixed = out.get("mixed_up") is True
    n = out.get("to")
    if out["fits"] or n == meant:
        return "fits", None, mixed
    if n == 0:
        return "general", None, mixed
    if isinstance(n, int) and 1 <= n <= count:
        return "other", n - 1, mixed
    return None, None, mixed


def named_first(lines, people):
    if not lines or not people:
        return None
    first, last = lines[0].lower(), lines[-1].lower()
    for name, msg in sorted(people.items(), key=lambda kv: -len(kv[0])):
        if len(name) < 3:
            continue
        n = re.escape(name)
        if re.match(rf"^@?{n}(?![\w])", first) or re.search(rf"[,\s]@?{n}\W*$", last):
            return msg
    return None


NO_PINGS_AT_ALL = re.compile(
    r"\b(?:no|stop|don'?t|never|quit)\b.{0,20}\bping(?:s|ing)?\b.{0,20}"
    r"\b(?:anyone|anybody|everyone|people|ppl|nobody|no ?one|at all)\b|\bno more pings\b",
    re.I,
)


def ping_forbidden(orders, names):
    names = {str(n).lower() for n in names if n and len(str(n)) >= 3}
    for text in orders:
        t = str(text).lower()
        if "ping" not in t:
            continue
        if NO_PINGS_AT_ALL.search(t):
            return True
        if re.search(r"\b(?:no|stop|don'?t|never|quit|dont)\b", t) and any(
            re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", t) for n in names
        ):
            return True
    return False


def add_ping(lines, user_id, at_end=False):
    if not lines:
        return lines
    tag = f"<@{user_id}>"
    lines = list(lines)
    if any(tag in ln for ln in lines):
        return lines
    i = next((i for i, ln in enumerate(lines) if not ln.startswith("[sticker:")), None)
    if i is None:
        return lines
    if at_end:
        j = max(k for k, ln in enumerate(lines) if not ln.startswith("[sticker:"))
        lines[j] = lines[j] + " " + tag
    else:
        lines[i] = tag + " " + lines[i]
    return lines


AT_NAME = re.compile(r"(?<![\w@<])@([A-Za-z][\w.]{1,31})")


def real_pings(line, people, allowed):
    pinged = []

    def swap(m):
        name = m.group(1).rstrip(".")
        rest = m.group(1)[len(name) :]
        user = people.get(name.lower())
        if user is None or not allowed(user):
            return name + rest
        pinged.append(user)
        return f"<@{user.id}>" + rest

    return AT_NAME.sub(swap, line), pinged
