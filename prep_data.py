import json
import os
import random
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

from mitski.brain.answers import STOP
from mitski.brain.prompts import ANSWER_NOTE
from mitski.config.schema import OPTIONS
from mitski.llm.prompt_format import Format

INPUT = "data/messages.jsonl"
TRAIN_OUT = "data/train.jsonl"
VAL_OUT = "data/val.jsonl"
PREVIEW_OUT = "data/preview.txt"
PERSONA_OUT = "data/persona.yaml"
CONFIG = "config/mitski.yaml"
NAME = OPTIONS["NAME_TRIGGERS"].default[0]

VAL_SPLIT = 0.06
SESSION_GAP_MIN = 30
CONTEXT_TURNS = 10
LEARN_TURNS = 6
MAX_CHARS = 4000
EXCLUDE_CHANNELS = []
MAX_OTHER_CHARS = 500

NOTES_SHARE = 0.75
BRIEF_SHARE = 0.5
BRIEF_MAX_WORDS = 6
FILLER = set(
    [
        "lol",
        "lmao",
        "lmfao",
        "bro",
        "bruh",
        "ngl",
        "fr",
        "tbh",
        "idk",
        "like",
        "yeah",
        "ya",
        "yea",
        "ok",
        "okay",
        "oh",
        "omg",
        "wait",
        "huh",
        "hmm",
        "um",
        "uh",
        "just",
        "so",
        "really",
        "kinda",
        "lowkey",
        "highkey",
        "literally",
        "dude",
        "girl",
        "haha",
        "hehe",
        "xd",
        "rn",
        "u",
        "ur",
    ]
)
NAMES_SHARE = 0.65
SYSTEM_EXTRAS_SHARE = 0.6
KEEP_SMALL = 0.45
MAX_SAME = 3
DROP_ABOUT_HER = True
DROP_WORDS = [
    "nigger",
    "niggers",
    "nigga",
    "niggas",
    "wigga",
    "wiggas",
    "faggot",
    "faggots",
    "fag",
    "fags",
    "tranny",
    "trannies",
    "retard",
    "retards",
    "retarded",
]
SEED = 3407

PERSONA_FROM = "config"
PERSONA = OPTIONS["PERSONA"].default
STYLE_NOTE = OPTIONS["STYLE_NOTE"].default

FMT = Format("qwen")
SPECIAL = re.compile(
    r"<\|[A-Za-z0-9_]{1,40}\|>|</?think>|\[/?(?:INST|SYSTEM_PROMPT|AVAILABLE_TOOLS|TOOL_RESULTS|"
    r"TOOL_CALLS)\]|</?s>"
)
NAME_KEYS = ("author_name", "author", "display_name", "name", "username")
POOL = [
    "skye",
    "jay",
    "nova",
    "milo",
    "rex",
    "zoe",
    "ash",
    "leo",
    "luna",
    "kira",
    "finn",
    "ivy",
    "theo",
    "mia",
    "nico",
    "jules",
    "cass",
    "remy",
    "sol",
    "bea",
    "koda",
    "juno",
    "otto",
    "pip",
    "rory",
    "wren",
    "dex",
    "yuki",
    "lux",
    "max",
    "nyx",
    "toby",
    "ella",
    "kai",
    "rin",
    "vex",
    "momo",
    "zane",
    "lia",
    "oli",
]
SMALL = re.compile(
    r"^(?:lo+l+|lma+o+|lmfa+o+|ha(?:ha)+h?|he(?:he)+|xd+|ok(?:ay)?|kk?|ya|yea|yeah|yes|no+|nah|wut|"
    r"what|huh|fr|true|real|same|bet|:\w{2,32}:|[\W_]{1,6})[\s!?.]*$",
    re.I,
)
MINOR = re.compile(r"\b(?:minors?|underage|under ?age|loli|lolis|pedo\w*|groom(?:ed|ing|er|s)?|child porn|cp)\b", re.I)
EMOJI_NAME = re.compile(r"(?<![\w:]):(\w{2,32}):(?![\w:])")
JUST_HI = re.compile(
    r"^\W*(?:@[\w.'-]{1,32}\W+)?(?:hi+|hey+|hello+|helo|yo+|sup|wsg|wassup|howdy|hiya|heya|hai|haii+|"
    r"gm|good\s*morning|morning|mornin|good\s*(?:evening|afternoon)|evening)\W*(?:@?[\w.'-]{1,32})?\W*$",
    re.I,
)
GREETS_BACK = re.compile(
    r"\b(?:hi+|hey+|hello+|yo+|sup|wsg|wassup|hiya|heya|hai+|gm|morning|mornin|evening|"
    r"welcome|wb)\b",
    re.I,
)


def load_config():
    if not os.path.exists(CONFIG):
        return {}
    try:
        import yaml

        with open(CONFIG, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"couldn't read {CONFIG} ({e})")
        return {}


def tidy(text, hers=False):
    text = SPECIAL.sub("", str(text or ""))
    if hers:
        text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"[ \t]*\n[ \t]*", "\n", text).strip()


def clip(text):
    return text if len(text) <= MAX_OTHER_CHARS else text[: MAX_OTHER_CHARS - 1].rstrip() + "…"


def who(c):
    for k in NAME_KEYS:
        v = c.get(k)
        if isinstance(v, dict):
            v = v.get("display_name") or v.get("global_name") or v.get("name")
        if isinstance(v, str) and v.strip():
            v = re.sub(r"\s*[\[\(\{].*?[\]\)\}]", "", v).strip() or v.strip()
            return re.sub(r"^[\W_]+|[\W_]+$", "", v) or v
    return ""


def load_records():
    records = []
    with open(INPUT, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("channel") in EXCLUDE_CHANNELS:
                continue
            records.append(r)
    records.sort(key=lambda r: int(r["id"]))
    return records


def others_since_last_target(record):
    ctx = record.get("context") or []
    last = max((i for i, c in enumerate(ctx) if c.get("speaker") == "target"), default=-1)
    others = [(who(c), clip(tidy(c.get("content")))) for c in ctx[last + 1 :] if c.get("speaker") == "other"]
    reply = record.get("reply_to")
    if reply and reply.get("speaker") == "other" and tidy(reply.get("content")) not in [t for _, t in others]:
        others.insert(0, (who(reply), tidy(reply.get("content"))))
    return [(n, t) for n, t in others if t]


class Turn:
    __slots__ = ("learn", "lines", "rec", "role", "why")

    def __init__(self, role, rec=None):
        self.role, self.lines, self.rec, self.learn, self.why = role, [], rec, True, ""

    @property
    def text(self):
        return "\n".join(t for _, t in self.lines)


def build_sessions(records):
    channels = defaultdict(list)
    for r in records:
        channels[(r.get("guild_id"), r.get("channel"))].append(r)
    sessions = []
    gap = timedelta(minutes=SESSION_GAP_MIN)
    for msgs in channels.values():
        turns, last_time = [], None
        for r in msgs:
            t = datetime.fromisoformat(r["timestamp"])
            if last_time is not None and t - last_time > gap and turns:
                sessions.append(turns)
                turns = []
            last_time = t
            for name, text in others_since_last_target(r):
                add(turns, "user", name, text, r)
            mine = tidy(r.get("content"), hers=True)
            if mine:
                add(turns, "assistant", "", mine, r)
        if turns:
            sessions.append(turns)
    out = []
    for turns in sessions:
        while turns and turns[0].role == "assistant":
            turns = turns[1:]
        if any(t.role == "assistant" for t in turns):
            out.append(turns)
    return out


def add(turns, role, name, text, rec):
    if not turns or turns[-1].role != role:
        turns.append(Turn(role, rec))
    turns[-1].lines.append((name, text))
    if role == "assistant":
        turns[-1].rec = rec


def dropper():
    return (
        re.compile(r"(?<![a-z])(?:" + "|".join(map(re.escape, DROP_WORDS)) + r")(?![a-z])", re.I)
        if DROP_WORDS
        else None
    )


def judge(sessions, rng):
    drop = dropper()
    about_her = re.compile(r"\b" + re.escape(NAME) + r"\b", re.I)
    seen = Counter()
    why = Counter()
    for turns in sessions:
        for t in turns:
            if t.role != "assistant":
                continue
            text = t.text
            norm = re.sub(r"\W+", " ", text.lower()).strip()
            if DROP_ABOUT_HER and about_her.search(text):
                t.learn, t.why = False, "talks about mitski"
            elif MINOR.search(text):
                t.learn, t.why = False, "minors"
            elif drop is not None and drop.search(text):
                t.learn, t.why = False, "DROP_WORDS"
            elif seen[norm] >= MAX_SAME and norm:
                t.learn, t.why = False, f"said {MAX_SAME}+ times already"
            elif (len(text) <= 6 or SMALL.match(text)) and "\n" not in text and rng.random() >= KEEP_SMALL:
                t.learn, t.why = False, "tiny (KEEP_SMALL)"
            seen[norm] += 1
            why[t.why or "learned"] += 1
    return why


def windows(turns):
    learnable = [i for i, t in enumerate(turns) if t.role == "assistant" and t.learn]
    out, i = [], 0
    while i < len(learnable):
        n = min(LEARN_TURNS, len(learnable) - i)
        while True:
            group = learnable[i : i + n]
            end = group[-1]
            start = max(0, group[0] - CONTEXT_TURNS)
            while start < group[0] - 1 and size(turns[start : end + 1]) > MAX_CHARS:
                start += 1
            while turns[start].role != "user":
                start += 1
            if size(turns[start : end + 1]) <= MAX_CHARS or n == 1:
                break
            n -= 1
        out.append((start, end, group))
        i += n
    return out


def size(turns):
    return sum(len(n) + len(t) + 3 for turn in turns for n, t in turn.lines)


def local(ts, tz):
    t = datetime.fromisoformat(ts)
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return t.astimezone(tz)


def time_phrase(now):
    h = now.hour
    part = (
        "in the middle of the night"
        if h < 5
        else "early in the morning"
        if h < 8
        else "in the morning"
        if h < 11
        else "around midday"
        if h < 14
        else "in the afternoon"
        if h < 18
        else "in the evening"
        if h < 22
        else "late at night"
    )
    return f"It's {now.strftime('%A')} {part} ({now.strftime('%H:%M')})."


def name_people(window, rng, real_names):
    if real_names:
        return [[n for n, _ in t.lines] if t.role == "user" else [] for t in window]
    cast = rng.sample(POOL, rng.randint(2, 4))
    weights = [3] + [1] * (len(cast) - 1)
    out, prev = [], None
    for t in window:
        if t.role != "user":
            out.append([])
            continue
        names = []
        for _ in t.lines:
            if prev is not None and rng.random() < 0.55:
                n = prev
            else:
                n = rng.choices(cast, weights)[0]
            names.append(n)
            prev = n
        out.append(names)
    return out


def emoji_ranking(records):
    per_guild = defaultdict(Counter)
    for r in records:
        g = r.get("guild_id")
        for text in [r.get("content")] + [c.get("content") for c in r.get("context") or []]:
            for e in EMOJI_NAME.findall(str(text or "")):
                per_guild[g][e] += 1
    drop = dropper()
    return {g: [e for e, _ in c.most_common() if not (drop and drop.search(e))] for g, c in per_guild.items()}


def brief_of(said, reply):
    if "?" not in said or JUST_HI.match(said) or reply.rstrip().endswith("?"):
        return None
    text = EMOJI_NAME.sub(" ", reply.lower())
    words = [w for w in dict.fromkeys(re.findall(r"[a-z0-9][a-z0-9']*", text)) if w not in STOP and w not in FILLER]
    if not 1 <= len(words) <= BRIEF_MAX_WORDS:
        return None
    return " ".join(words)


def example(turns, start, end, learn, rng, tz, emojis):
    window = turns[start : end + 1]
    real_names = any(n for t in window if t.role == "user" for n, _ in t.lines)
    use_names = real_names or rng.random() < NAMES_SHARE
    names = name_people(window, rng, real_names) if use_names else None
    msgs = []
    for k, t in enumerate(window):
        if t.role == "user":
            lines = [f"{names[k][i]}: {text}" if names and names[k][i] else text for i, (_, text) in enumerate(t.lines)]
            msgs.append({"role": "user", "content": "\n".join(lines)})
        else:
            msgs.append({"role": "assistant", "content": t.text})
    hers = [k for k, t in enumerate(window) if t.role == "assistant"]
    learn_idx = [hers.index(j - start) for j in learn]

    last_user = max(k for k, t in enumerate(window) if t.role == "user")
    speakers = []
    if names:
        for k in range(len(window) - 1, -1, -1):
            for n in reversed(names[k]):
                if n and n not in speakers:
                    speakers.append(n)
    call = names[last_user][-1] if names else None
    last = window[-1]
    rec = last.rec or {}

    system = PERSONA
    if rng.random() < SYSTEM_EXTRAS_SHARE:
        extras = []
        if call:
            extras.append(
                rng.choice(
                    [
                        f"You're talking with {call}, you don't really know them yet. You haven't talked before, so there's "
                        f"nothing you remember with them.",
                        f"You're talking with {call}, someone you've talked to a few times.",
                        f"You're talking with {call}, a friend of yours.",
                        f"You're talking with {call}, one of your close friends.",
                    ]
                )
            )
        ranked = emojis.get(rec.get("guild_id"), [])
        if ranked:
            used = [e for t in window if t.role == "assistant" for e in EMOJI_NAME.findall(t.text)]
            listed = ranked[:20]
            for e in dict.fromkeys(used):
                if e not in listed:
                    listed.insert(rng.randint(0, len(listed)), e)
            extras.append("Custom emojis on this server you can use: " + " ".join(f":{e}:" for e in listed))
        system = "\n\n".join([PERSONA] + extras)

    notes = None
    if rng.random() < NOTES_SHARE:
        lines = ["(notes only you can see, for your next message)"]
        if rec.get("timestamp"):
            lines.append(time_phrase(local(rec["timestamp"], tz)))
        where = f"#{rec.get('channel') or 'general'}" + (f" on {rec['guild']}" if rec.get("guild") else "")
        others = [s for s in speakers if s != call][:4]
        lines.append(
            f"You're chatting in {where}"
            + (f" with {call}" + (f", {', '.join(others)}" if others else "") if call else "")
            + "."
        )
        said = window[last_user].lines[-1][1]
        reply = last.text
        if JUST_HI.match(said) and GREETS_BACK.search(reply):
            lines.append(
                f"{call + ' is' if call else 'They are'} just saying hi, so say hi back (you can ask how they're doing). Don't "
                f"jump to a random question or a new topic."
            )
        elif len(said) < 25 and "?" not in said and len(reply) < 40:
            lines.append("It's a short message, so a short reply fits.")
        brief = brief_of(said, reply)
        if brief and rng.random() < BRIEF_SHARE:
            lines.append(ANSWER_NOTE.format(brief=brief))
        if STYLE_NOTE:
            lines.append(STYLE_NOTE)
        lines.append("Use these notes only where they fit, the way a real person would, and never mention them.")
        notes = "\n".join(lines)
    return {"messages": [{"role": "system", "content": system}] + msgs, "notes": notes, "learn": learn_idx}


def write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def preview(rows, n=4):
    out = []
    for row in rows[:n]:
        text, spans = FMT.training_parts(row["messages"], row.get("notes"), row.get("learn"))
        marked, pos = [], 0
        for a, b in spans:
            marked += [text[pos:a], "⟦", text[a:b], "⟧"]
            pos = b
        marked.append(text[pos:])
        out.append("".join(marked))
    os.makedirs(os.path.dirname(PREVIEW_OUT) or ".", exist_ok=True)
    with open(PREVIEW_OUT, "w", encoding="utf-8") as f:
        f.write(("\n\n" + "=" * 100 + "\n\n").join(out))


def yaml_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main():
    global NAME, PERSONA, STYLE_NOTE
    cfg = load_config()
    if isinstance(cfg.get("NAME_TRIGGERS"), list) and cfg["NAME_TRIGGERS"]:
        NAME = str(cfg["NAME_TRIGGERS"][0])
    tzname = str(cfg.get("TIMEZONE") or "").strip()
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tzname) if tzname else None
    except Exception:
        print(f"timezone {tzname!r} not found (on windows: pip install tzdata), using utc")
        tz = UTC
    if PERSONA_FROM == "config" and cfg.get("PERSONA"):
        PERSONA = str(cfg["PERSONA"]).strip()
        if cfg.get("STYLE_NOTE") is not None:
            STYLE_NOTE = str(cfg["STYLE_NOTE"]).strip()
        print(f"persona and style note: from {CONFIG}")
    else:
        print("persona and style note: the defaults from mitski/config/schema.py")

    rng = random.Random(SEED)
    records = load_records()
    sessions = build_sessions(records)
    why = judge(sessions, rng)
    emojis = emoji_ranking(records)

    order = list(range(len(sessions)))
    rng.shuffle(order)
    n_val = max(1, round(len(sessions) * VAL_SPLIT)) if len(sessions) > 20 else 0
    val_ids = set(order[:n_val])
    train, val = [], []
    for i, turns in enumerate(sessions):
        for start, end, learn in windows(turns):
            (val if i in val_ids else train).append(example(turns, start, end, learn, rng, tz, emojis))
    rng.shuffle(train)
    write_jsonl(TRAIN_OUT, train)
    write_jsonl(VAL_OUT, val)
    preview(train)
    with open(PERSONA_OUT, "w", encoding="utf-8") as f:
        f.write(
            "# the text she was trained with. config/mitski.yaml has to have these exact two lines, the bot has to\n"
            "# send her the same text\n"
            f"PERSONA: {yaml_str(PERSONA)}\nSTYLE_NOTE: {yaml_str(STYLE_NOTE)}\n"
        )

    learned = sum(len(r["learn"]) for r in train + val)
    hers = sum(why.values())
    print(
        f"{len(records)} of her messages -> {len(sessions)} conversations -> {len(train)} train / {len(val)} val examples"
    )
    print(f"her replies: {hers}, learned from: {learned}")
    for k, v in why.most_common():
        if k != "learned":
            print(f"  not learned, {k}: {v}")
    print(
        f"with notes: {sum(1 for r in train if r['notes'])}/{len(train)}, with names: "
        f"{sum(1 for r in train if re.search(r'(?m)^[^:]{1,20}: ', r['messages'][1]['content']))}/{len(train)}"
    )
    print(f"preview: {PREVIEW_OUT} (the parts she learns are in ⟦ ⟧)")
    if cfg.get("PERSONA") and str(cfg["PERSONA"]).strip() != PERSONA:
        print(
            f"\n!! the PERSONA in {CONFIG} is different from the one she's trained with. copy both lines from "
            f"{PERSONA_OUT} into it, or the lora won't sound right"
        )
    elif cfg.get("STYLE_NOTE") is not None and str(cfg["STYLE_NOTE"]).strip() != STYLE_NOTE:
        print(f"\n!! STYLE_NOTE in {CONFIG} is different from the training one, copy it from {PERSONA_OUT}")


if __name__ == "__main__":
    main()
