SLOTS = {
    "real_name": "their real first name",
    "nickname": "what they want to be called",
    "age": "their age, a number",
    "birthday": "their birthday, like march 3",
    "pronouns": "their pronouns",
    "location": "where they live now",
    "hometown": "where they're originally from",
    "job": "their job",
    "school": "their school or what they study",
    "relationship": "their relationship status or partner",
}


SLOT_LABELS = {
    "real_name": "real name",
    "nickname": "nickname",
    "age": "age",
    "birthday": "birthday",
    "pronouns": "pronouns",
    "location": "location",
    "hometown": "hometown",
    "job": "job",
    "school": "school",
    "relationship": "relationship status",
    "her_nick": "nickname you gave them",
}


SLOT_ALIASES = {
    "name": "real_name",
    "real name": "real_name",
    "irl name": "real_name",
    "first name": "real_name",
    "nick": "nickname",
    "called": "nickname",
    "preferred name": "nickname",
    "goes by": "nickname",
    "years": "age",
    "bday": "birthday",
    "birth day": "birthday",
    "birthdate": "birthday",
    "date of birth": "birthday",
    "pronoun": "pronouns",
    "lives": "location",
    "lives in": "location",
    "city": "location",
    "country": "location",
    "home": "location",
    "from": "hometown",
    "origin": "hometown",
    "work": "job",
    "occupation": "job",
    "study": "school",
    "studies": "school",
    "uni": "school",
    "university": "school",
    "college": "school",
    "major": "school",
    "grade": "school",
    "partner": "relationship",
    "dating": "relationship",
    "relationship status": "relationship",
    "her nick": "her_nick",
    "her nickname": "her_nick",
}


PUBLIC_CATEGORIES = {"likes", "dislikes", "games", "music", "media", "personality"}
CATEGORIES = {
    "life": 1.0,
    "people": 1.0,
    "plans": 1.1,
    "history": 0.95,
    "personality": 0.9,
    "likes": 0.8,
    "dislikes": 0.8,
    "games": 0.8,
    "music": 0.7,
    "media": 0.7,
    "other": 0.6,
}


STRENGTH = ["guess", "heard", "her", "said", "named", "asked"]


CAT_ALIASES = {
    "like": "likes",
    "hobby": "likes",
    "hobbies": "likes",
    "interests": "likes",
    "interest": "likes",
    "food": "likes",
    "dislike": "dislikes",
    "hates": "dislikes",
    "game": "games",
    "gaming": "games",
    "family": "people",
    "friends": "people",
    "friend": "people",
    "relationships": "people",
    "relationship": "people",
    "pets": "life",
    "pet": "life",
    "work": "life",
    "school": "life",
    "personal": "life",
    "health": "life",
    "traits": "personality",
    "trait": "personality",
    "inside joke": "history",
    "joke": "history",
    "jokes": "history",
    "shared": "history",
    "memories": "history",
    "memory": "history",
    "event": "plans",
    "events": "plans",
    "plan": "plans",
    "upcoming": "plans",
    "songs": "music",
    "artists": "music",
    "song": "music",
    "artist": "music",
    "band": "music",
    "bands": "music",
    "shows": "media",
    "show": "media",
    "anime": "media",
    "movies": "media",
    "movie": "media",
    "series": "media",
    "youtube": "media",
    "books": "media",
    "book": "media",
    "manga": "media",
}


MONTHS = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]


def _string(n):
    return {"type": "string", "maxLength": n}


BOND_MAX, SUMMARY_MAX, PORTRAIT_MAX, STYLE_MAX, HISTORY_MAX = 220, 420, 700, 340, 650


EVIDENCE = _string(160)


TAGS = {"type": "array", "maxItems": 5, "items": _string(24)}


FACT_ITEM = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": list(CATEGORIES)},
        "fact": _string(140),
        "tags": TAGS,
        "evidence": EVIDENCE,
        "date": _string(10),
    },
    "required": ["category", "fact", "tags", "evidence"],
    "additionalProperties": False,
}


PROFILE_ITEM = {
    "type": "object",
    "properties": {"value": _string(60), "evidence": EVIDENCE},
    "required": ["value", "evidence"],
    "additionalProperties": False,
}


SCHEMA = {
    "type": "object",
    "properties": {
        "profile": {"type": "object", "properties": dict.fromkeys(SLOTS, PROFILE_ITEM), "additionalProperties": False},
        "new_facts": {"type": "array", "items": FACT_ITEM, "maxItems": 6},
        "changed_facts": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "fact": _string(140),
                    "evidence": EVIDENCE,
                    "date": _string(10),
                },
                "required": ["id", "fact", "evidence"],
                "additionalProperties": False,
            },
        },
        "wrong_facts": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "evidence": EVIDENCE},
                "required": ["id", "evidence"],
                "additionalProperties": False,
            },
        },
        "her_nickname_for_them": _string(30),
        "their_name_for_her": _string(30),
        "bond": _string(BOND_MAX),
        "conversation": {
            "type": "object",
            "properties": {"summary": _string(SUMMARY_MAX), "mood": _string(60)},
            "required": ["summary", "mood"],
            "additionalProperties": False,
        },
        "new_threads": {"type": "array", "maxItems": 3, "items": _string(120)},
        "done_threads": {"type": "array", "maxItems": 5, "items": {"type": "integer"}},
        "about_her": {
            "type": "array",
            "maxItems": 4,
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": list(CATEGORIES)},
                    "fact": _string(140),
                    "evidence": EVIDENCE,
                },
                "required": ["category", "fact", "evidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "profile",
        "new_facts",
        "changed_facts",
        "wrong_facts",
        "her_nickname_for_them",
        "their_name_for_her",
        "bond",
        "conversation",
        "new_threads",
        "done_threads",
        "about_her",
    ],
    "additionalProperties": False,
}


SOURCED = {
    "type": "object",
    "properties": {"text": _string(140), "from": {"type": "array", "maxItems": 4, "items": _string(6)}},
    "required": ["text", "from"],
    "additionalProperties": False,
}


REFLECT = {
    "type": "object",
    "properties": {
        "portrait": _string(PORTRAIT_MAX),
        "talk_style": _string(STYLE_MAX),
        "inside_jokes": {"type": "array", "maxItems": 5, "items": SOURCED},
        "avoid": {"type": "array", "maxItems": 4, "items": SOURCED},
        "shared": {"type": "array", "maxItems": 5, "items": SOURCED},
        "merge": {
            "type": "array",
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "ids": {"type": "array", "minItems": 2, "maxItems": 4, "items": {"type": "integer"}},
                    "fact": _string(160),
                },
                "required": ["ids", "fact"],
                "additionalProperties": False,
            },
        },
        "forget": {"type": "array", "maxItems": 8, "items": {"type": "integer"}},
        "history": _string(HISTORY_MAX),
    },
    "required": ["portrait", "talk_style", "inside_jokes", "avoid", "shared", "merge", "forget", "history"],
    "additionalProperties": False,
}
