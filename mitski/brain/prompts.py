from mitski.core.text import cut
from mitski.core.texts import say, wording

TOOLS = wording("thinking.tools")
REPLY_TYPES = wording("thinking.reply_types")
ANSWERY = {"answer_question", "describe", "help", "opinion"}
PLANNED = ANSWERY | {"story"}
LENGTHS = ("short", "longer")
ASKS = ("none", "quick", "favor", "effort", "expert")
BRIEF_MAX = 600
MOODS = (
    "neutral",
    "happy",
    "excited",
    "proud",
    "playful",
    "flirty",
    "curious",
    "bored",
    "tired",
    "stressed",
    "nervous",
    "sad",
    "hurt",
    "annoyed",
    "angry",
    "confused",
)
PLAN = {
    "type": "object",
    "properties": {
        "to_her": {"type": "string", "enum": ["her", "someone_else", "everyone"]},
        "situation": {"type": "string", "maxLength": 240},
        "wants": {"type": "string", "maxLength": 160},
        "mood": {"type": "string", "enum": list(MOODS)},
        "subtext": {"type": "string", "maxLength": 160},
        "move": {"type": "string", "maxLength": 180},
        "follow_up": {"type": "string", "maxLength": 120},
        "reply_type": {"type": "string", "enum": list(REPLY_TYPES)},
        "length": {"type": "string", "enum": list(LENGTHS)},
        "ask": {"type": "string", "enum": list(ASKS)},
        "answer": {"type": "string", "maxLength": BRIEF_MAX},
        "tools": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "tool": {"type": "string", "enum": list(TOOLS)},
                    "input": {"type": "string", "maxLength": 120},
                },
                "required": ["tool", "input"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "to_her",
        "situation",
        "wants",
        "mood",
        "subtext",
        "move",
        "follow_up",
        "reply_type",
        "length",
        "ask",
        "answer",
        "tools",
    ],
    "additionalProperties": False,
}
REMIND = {
    "type": "object",
    "properties": {
        "who": {"type": "string", "maxLength": 40},
        "in_minutes": {"type": "integer", "minimum": 0, "maximum": 64800},
        "at_time": {"type": "string", "maxLength": 5},
        "on_date": {"type": "string", "maxLength": 10},
        "what": {"type": "string", "maxLength": 160},
    },
    "required": ["who", "in_minutes", "at_time", "on_date", "what"],
    "additionalProperties": False,
}


def plan_schema(n_parts, remind=False):
    base = PLAN
    props, required = dict(base["properties"]), list(base["required"])
    if n_parts >= 2:
        props["topics"] = {
            "type": "array",
            "maxItems": 5,
            "items": {"type": "integer", "minimum": 1, "maximum": n_parts},
        }
        required.append("topics")
    if remind:
        props["remind"] = REMIND
        required.append("remind")
    if props == base["properties"]:
        return base
    return {**base, "properties": props, "required": required}


BRIEF = {
    "type": "object",
    "properties": {"say": {"type": "string", "maxLength": 400}},
    "required": ["say"],
    "additionalProperties": False,
}


ANSWER_NOTE = wording("thinking.answer")
SKIPPED_LOOKUP_NOTE = wording("thinking.skipped_lookup")
STORY_NOTE = wording("thinking.story")


def available_tools(search=True, weather=True, vision=True, history=True):
    off = {"search": not search, "weather": not weather, "look_closer": not vision, "history": not history}
    return {k: v for k, v in TOOLS.items() if not off.get(k)}


def _newest_block(q):
    if len(q.parts) >= 2:
        listing = "\n".join(f'[{i}] "{cut(p, 200)}"' for i, p in enumerate(q.parts, 1))
        return say("thinking.newest_pieces", name=q.name, listing=listing, about=q.about) + "\n\n"
    several = wording("thinking.newest_several") if q.several else ""
    message = cut(q.newest, 400)
    return say("thinking.newest", name=q.name, several=several, message=message, about=q.about) + "\n\n"


def _to_her_block(q):
    if q.to_her == "her":
        return say("thinking.to_her_is_her", her=q.her) + "\n"
    if q.to_her == "someone_else":
        return say("thinking.to_her_someone_else", her=q.her) + "\n"
    return say("thinking.to_her_who", her=q.her, name=q.name) + "\n"


def _topics_block(q):
    if len(q.parts) < 2:
        return ""
    return say("thinking.topics", her=q.her) + "\n"


def _remind_block(q):
    if not q.remind:
        return ""
    return say("thinking.remind", her=q.her, name=q.name) + "\n"


def _search_block(tools):
    if "search" not in tools:
        return ""
    return "\n" + wording("thinking.search_hint")


def plan_request(q, tools, now):
    her, name = q.her, q.name
    system = say("thinking.plan_system", her=her, now=now.strftime("%A %Y-%m-%d %H:%M"))
    fields = say("thinking.plan_fields", her=her, name=name, moods=", ".join(MOODS), reply_types=", ".join(REPLY_TYPES))
    user = (
        say("thinking.recent_chat", recent=q.recent)
        + "\n\n"
        + (f"{q.knows}\n\n" if q.knows else "")
        + _newest_block(q)
        + _to_her_block(q)
        + _topics_block(q)
        + _remind_block(q)
        + fields
        + "\n"
        + "\n".join(f"- {k}: {v}" for k, v in tools.items())
        + _search_block(tools)
    )
    budget = 800 + (40 if len(q.parts) >= 2 else 0) + (80 if q.remind else 0)
    return system, user, plan_schema(len(q.parts), q.remind), budget


def brief_request(q, checked, answer):
    system = say("thinking.brief_system", her=q.her)
    user = (
        say("thinking.brief_asked", name=q.name, message=cut(q.newest, 300), checked="\n".join(checked))
        + ("\n\n" + say("thinking.brief_thought", answer=answer) if answer else "")
        + "\n\n"
        + say("thinking.brief_instruction", her=q.her, name=q.name)
    )
    return system, user, BRIEF, 240
