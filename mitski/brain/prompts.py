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
    "story": "They want a story, so tell one properly, the way you'd tell a friend something that happened to you.",
    "opinion": "They want your real opinion, so give one, don't dodge.",
    "help": "They want help, so help like a friend would: what you'd actually know or think, in your own words, not "
    "a full guide.",
    "comfort": "They're not doing great, be there for them for real.",
    "joke": "They're joking around, play along.",
    "greeting": "",
    "no_reply": "",
    "other": "",
}
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
SKIPPED_LOOKUP_NOTE = (
    "You don't know this offhand, and you're not looking it up right now. Say so the way a person would (no clue, "
    "idk tbh, google it lol), and don't make anything up."
)
STORY_NOTE = (
    "What happened, roughly: {brief}. Tell it as your own story, your way, with the funny bits in, like you're "
    "telling a friend."
)


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
        f"topics: which of those numbered pieces are separate QUESTIONS or requests that each need their own "
        f"answer from {q.her}, like [1, 2]. Remarks, reactions, jokes, emojis and comments are never their own "
        f"topic: a few of those in a row get one reply to the whole thing, so -> just the main piece, like [1]. "
        f'One thing said over a few pieces, or one question plus "hihi", "lol", "wait", "😭" or a follow-up about '
        f"the same thing -> just the main one.\n"
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
        f'Answer with JSON: {{"to_her": "...", "wants": "...", "mood": "...", "subtext": "...", "move": "...", '
        f'"follow_up": "...", "reply_type": "...", "length": "...", "ask": "...", "answer": "...", '
        f'"tools": [{{"tool": "...", "input": "..."}}]}}'
    )
    user = (
        f"Recent chat:\n{q.recent}\n\n"
        + (f"{q.knows}\n\n" if q.knows else "")
        + _newest_block(q)
        + _to_her_block(q)
        + _topics_block(q)
        + _remind_block(q)
        + f"Read {name} the way a friend who knows them would, from their words, their tone and what you know "
        f'about them. In everything you write here, {her} is "you" and "your", never her name or "she".\n'
        f"wants: one short sentence on what {name} wants from you with this message, as specific as you can. "
        f'Not just "to chat": what kind (to share good news and have you hype it, to vent and be listened to, '
        f"to get your honest take, to tease you and be teased back, to make plans, to feel included, to know "
        f"you're still around, to keep the bit going).\n"
        f"mood: how {name} seems right now, one of {', '.join(MOODS)}. Go by how they write as well as what they "
        f'say (lots of caps and "!!" vs short flat replies). neutral when there\'s no clear sign.\n'
        f"subtext: what's under it, if anything, in one short sentence: what they're not saying outright (they're "
        f"nervous about it and want to hear it'll be fine, they're fishing for a compliment, they feel left out, "
        f"they're testing if you remember). \"\" when it's just what it says, which is most of the time.\n"
        f"move: what you'll do in your reply, in one short sentence, the way a good friend who knows them would "
        f'("hype it up, then ask how it went", "tease back, he started it", "just be there, no advice unless '
        f'he asks", "answer, then get back to the game talk", "laugh and move on"). Fit it to what they want, '
        f"their mood, what you know about them, how you feel about them and your own mood. Not every reply needs a "
        f"question, and a reply can just be a reaction.\n"
        f"follow_up: a question you'd genuinely want to ask them next, only if you're actually curious and you "
        f'haven\'t just asked one yourself (look at the chat). Specific to them, not a generic "how are you". '
        f'"" most of the time.\n'
        f"reply_type: one of {', '.join(REPLY_TYPES)}. story when they ask her to tell a story, a joke or something "
        f"funny or interesting that happened (joke is for when they're the ones joking around). no_reply if it "
        f"doesn't need an answer from her at all.\n"
        f'length: "short" almost always: chatting, jokes, reactions, greetings and quick questions get a quick line '
        f'or two. "longer" only when a good reply really needs more than that: they asked her to explain or '
        f"describe something properly, want advice or help with specifics, asked for a story (how her trip, exam "
        f"or day went), are going through something and need her to really be there, or wrote a long, thoughtful "
        f"message that deserves a real answer.\n"
        f'ask: what they\'re asking of her, if anything. "none": nothing, just chatting or a remark. "quick": '
        f"something she can answer offhand (her favourite cake, her opinion, something most people know). "
        f'"favor": something she can just do for them (remind someone, hop in vc, ping or dm someone, change her '
        f'status). "effort": something that takes real work to do properly: a whole recipe, a step by step guide, '
        f"an essay or homework, code, a long translation, a list of ten things, a detailed explanation. People in "
        f"a chat don't do those on demand. \"expert\": a specific or technical fact she wouldn't know without "
        f"looking it up. A message can ask two things: pick the bigger one (a favourite cake AND a recipe = "
        f"effort).\n"
        f"answer: if they ask something {her} can answer from what she knows or what's in the chat, the gist of "
        f"the answer as a short note of what she'd say, in her own voice: when it's about {her} herself it's "
        f'"i" and "my", never her name or "she" (like "canberra, not sydney" or "yes, i\'m still here"). A note, '
        f"not a message: no greeting, and nothing about their feelings or private stuff unless they asked. For a "
        f"story, what happens in it, start to end, in a few sentences. For an effort ask, only the gist she'd know "
        f'offhand in a few words (like "lemon drizzle, it\'s just a sponge with lemon syrup"), never the whole '
        f"thing. "
        f"\"\" if it's just chatting, a greeting, or she needs a tool to find out. Her own earlier messages aren't "
        f"facts she has to stick to: if she said something odd or random and they're confused by it, the answer can "
        f'be her laughing it off ("lmao idk what i was on about") instead of repeating it.\n'
        f"tools she can use first (none if she doesn't need any, at most 3). remember is for things about "
        f"{name} or her past chats with them that aren't in the recent chat, recall is for OTHER people they "
        f"mention:\n" + "\n".join(f"- {k}: {v}" for k, v in tools.items()) + _search_block(tools) + _owner_block(q)
    )
    budget = (900 if q.owner else 800) + (40 if len(q.parts) >= 2 else 0) + (80 if q.remind else 0)
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
    return system, user, BRIEF, 240
