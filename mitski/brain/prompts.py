from mitski.core.text import cut

TOOLS = {
    "search": "google something: news, game updates and patches, esports or sports results, prices, release dates, "
    "real people, specific facts, a game/song/show/meme/streamer she doesn't know, anything she'd have to "
    "check, or just something she's curious about. input = a short google query",
    "weather": "the current weather and today's forecast somewhere. input = the place",
    "time": "what time it is somewhere right now. input = the place",
    "calc": "work out some math. input = the expression, like 17*23 or (120-35)/4",
    "look_closer": "look carefully at the image/gif/video/sticker in the chat, when they ask about it or want it "
    "described or explained. input = what they want to know about it",
    "recall": "what she remembers about ANOTHER person they mentioned. input = that person's name",
    "remember": "search her memory of the person she's talking to and her past chats with them, when they bring up "
    'something from before or ask if she remembers something ("remember when..", "what did i tell u '
    'about..", "do u remember my.."). input = what to look for',
    "history": "scroll back through this channel's older messages, when they mention something said earlier that "
    'isn\'t in the recent chat. input = what to look for, like "sam new pc" or "the tournament link"',
}
REPLY_TYPES = {
    "small_talk": "",
    "answer_question": "They want an actual answer, so give it properly, with the facts you checked if you checked any.",
    "describe": "They want you to describe or explain it, so actually do that in a couple of sentences, in your own words.",
    "opinion": "They want your real opinion, so give one, don't dodge.",
    "help": "They want help, so actually help, with specifics.",
    "comfort": "They're not doing great, be there for them for real.",
    "joke": "They're joking around, play along.",
    "greeting": "",
    "no_reply": "",
    "other": "",
}
ANSWERY = {"answer_question", "describe", "help", "opinion"}
PLAN = {
    "type": "object",
    "properties": {
        "to_her": {"type": "string", "enum": ["her", "someone_else", "everyone"]},
        "wants": {"type": "string", "maxLength": 160},
        "reply_type": {"type": "string", "enum": list(REPLY_TYPES)},
        "answer": {"type": "string", "maxLength": 300},
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
    "required": ["to_her", "wants", "reply_type", "answer", "tools"],
    "additionalProperties": False,
}
PLAN_OWNER = {
    **PLAN,
    "properties": {
        **PLAN["properties"],
        "order": {"type": "string", "maxLength": 200},
        "drop_orders": {"type": "array", "maxItems": 5, "items": {"type": "integer"}},
        "quiet_minutes": {"type": "integer", "minimum": -1, "maximum": 1440},
        "status": {"type": "string", "maxLength": 120},
        "dm_who": {"type": "string", "maxLength": 40},
        "dm_say": {"type": "string", "maxLength": 300},
    },
    "required": PLAN["required"] + ["order", "drop_orders", "quiet_minutes", "status", "dm_who", "dm_say"],
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


def plan_schema(owner, n_parts, remind=False):
    base = PLAN_OWNER if owner else PLAN
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


ANSWER_NOTE = "What to tell them: {brief}. Say it your way, and actually answer instead of just asking something back."


def available_tools(search=True, weather=True, vision=True, history=True):
    off = {"search": not search, "weather": not weather, "look_closer": not vision, "history": not history}
    return {k: v for k, v in TOOLS.items() if not off.get(k)}


def _newest_block(q):
    if len(q.parts) >= 2:
        listing = "\n".join(f'[{i}] "{cut(p, 200)}"' for i, p in enumerate(q.parts, 1))
        return f"What {q.name} just said, piece by piece:\n{listing}{q.about}\n\n"
    several = " (a few in a row, all one thing to answer)" if q.several else ""
    return f'{q.name}\'s newest message{several}: "{cut(q.newest, 400)}"{q.about}\n\n'


def _to_her_block(q):
    her, name = q.her, q.name
    if q.to_her == "her":
        return (
            f'to_her: "her". (that message is to {her}: they pinged her, replied to her, or are in the middle of '
            f'talking with her, so even a short "ok" or "ill look into it" is them answering her)\n'
        )
    if q.to_her == "someone_else":
        return f'to_her: "someone_else". (that message is to someone else, {her} is only chiming in)\n'
    return (
        f'to_her: who is {name} talking to in that newest message? "her" if it\'s to {her} (or continues their '
        f'chat with her, like answering what she just said), "someone_else" if it\'s to another person (like '
        f'"gm sam" or answering someone else), "everyone" if it\'s to the whole chat.\n'
    )


def _topics_block(q):
    if len(q.parts) < 2:
        return ""
    return (
        f"topics: which of those numbered pieces each need their own answer from {q.her}. Different questions "
        f"or topics -> all of their numbers, like [1, 2] or [1, 2, 3]. One thing said over a few pieces, or one "
        f'real piece plus "hihi", "lol", "wait" or a follow-up about the same thing -> just the main one, '
        f"like [1].\n"
    )


def _remind_block(q):
    if not q.remind:
        return ""
    return (
        f'remind: they want {q.her} to remind someone of something later, like "remind me in 2h to drink '
        f'water" or "remind sam at 8 to start the raid". who: "me" if it\'s for {q.name}, else the other '
        f'person\'s name. in_minutes: minutes from now if they said "in ...", else 0. at_time: "HH:MM" '
        f'(24h) if they said a time of day, else "". on_date: "YYYY-MM-DD" if they said a day (tomorrow, '
        f'friday, ...), else "". what: what to remind them about, short ("drink water", "start the raid"). '
        f'If it isn\'t a reminder request after all, what = "".\n'
    )


def _search_block(tools):
    if "search" not in tools:
        return ""
    return (
        "\nGoogle instead of guessing: her own knowledge stops around mid 2026 and she isn't an encyclopedia, "
        "so for anything current (news, updates, patches, releases, results, prices), anything about a "
        "specific real person, game, song or show she isn't sure about, or when they ask her to look it up, "
        "use search and leave answer empty. She can also google something just because she's curious about "
        "what they brought up."
    )


def _owner_block(q):
    if not q.owner:
        return ""
    name, her = q.name, q.her
    return (
        f"\n\n{name} is {her}'s owner: she listens to them above everyone and does what they ask. Their "
        f"standing orders right now:\n{q.orders or '(none)'}\n"
        f'order: if {name} tells her how to behave from now on (a lasting rule like "stop pinging sam", '
        f'"call anna princess", "no more gifs"), that rule written short, to her. "" for one-off requests.\n'
        f'drop_orders: numbers of standing orders {name} takes back ("you can ping sam again").\n'
        f"quiet_minutes: if {name} tells her to be quiet, shut up or stop chatting for a while, for how many "
        f"minutes (30 if they don't say). -1 if they say she can talk again, speak again or stop being quiet. "
        f"0 otherwise.\n"
        f'status: if {name} tells her to change her discord status, the new one ("playing valorant", '
        f'"listening to laufey", "watching anime", or "clear"). "" otherwise.\n'
        f'dm_who and dm_say: if {name} tells her to dm someone, who (their name) and what to tell them. "" otherwise.'
    )


def plan_request(q, tools, now):
    her, name = q.her, q.name
    system = (
        f"You're {her}'s quick inner thoughts right before she replies on discord. She's a real person in a group "
        f"chat: she works out who a message is for, what they want, checks things on her phone when she needs to, "
        f"and then actually answers instead of dodging. It's {now.strftime('%A %Y-%m-%d %H:%M')} where she is. "
        f'Answer with JSON: {{"to_her": "...", "wants": "...", "reply_type": "...", '
        f'"answer": "...", "tools": [{{"tool": "...", "input": "..."}}]}}'
    )
    user = (
        f"Recent chat:\n{q.recent}\n\n"
        + _newest_block(q)
        + _to_her_block(q)
        + _topics_block(q)
        + _remind_block(q)
        + f'wants: one short sentence on what {name} wants. {her} is "you" here (like "to know if you\'re still '
        f'here"), never her name or "she".\n'
        f"reply_type: one of {', '.join(REPLY_TYPES)}. no_reply if it doesn't need an answer from her at all.\n"
        f"answer: if they ask something {her} can answer from what she knows or what's in the chat, the gist of "
        f"the answer as a short note of what she'd say, in her own voice: when it's about {her} herself it's "
        f'"i" and "my", never her name or "she" (like "canberra, not sydney" or "yes, i\'m still here"). A note, '
        f"not a message: no greeting, and nothing about their feelings or private stuff unless they asked. "
        f'"" if it\'s just chatting, a greeting, or she needs a tool to find out.\n'
        f"tools she can use first (none if she doesn't need any, at most 3). remember is for things about "
        f"{name} or her past chats with them that aren't in the recent chat, recall is for OTHER people they "
        f"mention:\n" + "\n".join(f"- {k}: {v}" for k, v in tools.items()) + _search_block(tools) + _owner_block(q)
    )
    budget = (380 if q.owner else 300) + (20 if len(q.parts) >= 2 else 0) + (60 if q.remind else 0)
    return system, user, plan_schema(q.owner, len(q.parts), q.remind), budget


def brief_request(q, checked, answer):
    system = f'You help {q.her} answer a message on discord. Answer with JSON: {{"say": "..."}}.'
    user = (
        f'{q.name} asked: "{cut(q.newest, 300)}"\n\nWhat she found out:\n'
        + "\n".join(checked)
        + (f"\n\nWhat she already thought: {answer}" if answer else "")
        + f"\n\nAs a short note (max 25 words), what's the answer she should give {q.name}? "
        f'Just the facts, like "Vitality won, 2-1 vs Spirit in Cologne". Not a message: no greeting, nothing '
        f'about their feelings. Anything about {q.her} herself is "i" and "my", never her name or "she". '
        f"If what she found doesn't answer it, write \"couldn't find out\"."
    )
    return system, user, BRIEF, 120
