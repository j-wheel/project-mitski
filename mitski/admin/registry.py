from dataclasses import dataclass

from mitski.core.text import snowflakes


@dataclass(frozen=True)
class Command:
    name: str
    aliases: tuple
    args: str
    about: str


GROUPS = (
    (
        "channels",
        (
            Command("addchannel", ("ac", "addchannels"), "<id ...>", "add channels she talks in"),
            Command("delchannel", ("dc", "delchannels", "removechannel"), "<id ...>", "remove channels she talks in"),
            Command("listchannels", ("lc", "listchannel", "channels"), "", "list her channels"),
        ),
    ),
    (
        "users",
        (
            Command("ignoreuser", ("iu", "ignoreusers"), "<id ...>", "ignore users completely (also forgets them)"),
            Command("unignoreuser", ("uu", "unignoreusers"), "<id ...>", "stop ignoring users"),
            Command("listusers", ("lu", "ignored"), "", "list ignored users"),
        ),
    ),
    (
        "memory",
        (
            Command("mem", ("m",), "<who>", "what she remembers (also: self, update, reflect, raw, search)"),
            Command(
                "forget", ("fg",), "<who> <what>", "forget a fact (F3), a field (age, portrait) or everything (all)"
            ),
            Command("note", ("n",), "<who> [cat] <fact>", "add a fact by hand"),
            Command("set", ("sf",), "<who> <field> <value>", "set a profile field"),
            Command("forgetme", ("fm",), "", "she deletes what she knows about you and stops remembering new things"),
            Command("rememberme", ("rm",), "", "undo forgetme"),
        ),
    ),
    (
        "sleep",
        (
            Command("sleep", ("sl",), "<server> [hours]", "send her away from a server for a while"),
            Command("wake", ("wk",), "<server|all>", "bring her back"),
            Command("sleepexclude", ("se", "nosleep"), "<server ...>", "servers she never goes away from by herself"),
            Command("sleepinclude", ("si",), "<server ...>", "undo sleepexclude"),
            Command("listsleep", ("ls", "sleepstatus"), "", "sleep settings, and where she's asleep or quiet now"),
        ),
    ),
    (
        "her day",
        (
            Command("reminders", ("rem",), "[cancel <n>|clear]", "list or cancel pending reminders"),
            Command(
                "routine",
                ("rt",),
                "[redo]",
                "what she's doing now and her plan for the next 24 hours (redo: plan again)",
            ),
            Command("busy", ("bz",), "<min> [what]", "make her busy for a while"),
            Command("free", ("fr",), "[min]", "make her free for a while, whatever her plan says"),
        ),
    ),
    (
        "owner",
        (
            Command("orders", ("ord",), "[add <rule>|forget <n>|clear]", "list or change her standing orders"),
            Command("quiet", ("q",), "<min|off> [server]", "completely quiet in a server, or everywhere without one"),
        ),
    ),
    (
        "bot",
        (
            Command("stats", ("st",), "", "reply latency, llm calls per reply, time per stage, fallbacks"),
            Command("prefix", ("px", "setprefix"), "[new]", "show or change what commands start with"),
            Command("help", ("h", "commands"), "", "this list"),
        ),
    ),
)
LOOKUP = {
    word: command.name
    for _title, commands in GROUPS
    for command in commands
    for word in (command.name, *command.aliases)
}
PHRASES = {"forget me": "forgetme", "remember me": "rememberme"}


@dataclass
class Invocation:
    cmd: str
    name: str
    rest: str
    ids: list


def parse(text, prefix):
    text = (text or "").strip()
    if text[: len(prefix)].lower() != prefix.lower():
        return None
    head = text.split(maxsplit=1)[0]
    word, rest = head[len(prefix) :].lower(), text[len(head) :]
    name = PHRASES.get(f"{word} {rest.strip().lower()}") or LOOKUP.get(word)
    if name is None:
        return None
    return Invocation(head.lower(), name, rest, snowflakes(rest))


def help_text(prefix):
    blocks = [f"**commands** (prefix `{prefix}`)"]
    for title, commands in GROUPS:
        lines = [f"**{title}**"]
        for c in commands:
            usage = f"{prefix}{c.name} {c.args}".strip()
            aliases = " · ".join(f"`{prefix}{a}`" for a in c.aliases)
            lines += [f"`{usage}` · {aliases}", f"-# {c.about}"]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
