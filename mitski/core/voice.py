import re
from functools import lru_cache

SECOND_PERSON = re.compile(r"\b(?:u|ya|you|youre|you're|ur|your|yours)\b", re.I)
THIRD_PERSON = re.compile(r"\b(?:she|shes|she's|her|hers|he|hes|he's|him|his|they|them|their)\b", re.I)
OTHER_PERSON = re.compile(r"\b(?:he|he's|him|his|they|they're|them|their|theirs)\b", re.I)
SHE_WORD = re.compile(r"\b(?:she|she's|her|hers|herself)\b", re.I)
OPENS_WITH_SHE = re.compile(
    r"^\W*(?:(?:yes|yeah|yea|ya|yep|no|nah|nope|lol|lmao|ok|okay|idk|well|hmm|bro|ngl|tbh|fr)\W+)*(?:she|she's|shes)\b",
    re.I,
)
ARTIST_WORDS = r"albums?|songs?|tracks?|lyrics?|concerts?|tour|playlists?|music|discography"
CONTRACTED_IS = frozenset(
    [
        "being",
        "going",
        "doing",
        "not",
        "here",
        "so",
        "really",
        "very",
        "still",
        "just",
        "always",
        "gonna",
        "a",
        "an",
        "the",
        "in",
        "on",
        "at",
        "too",
        "kinda",
        "lowkey",
    ]
)
CONTRACTED_HAS = frozenset({"been", "got", "gotten", "done", "gone", "had", "played", "seen", "said", "made"})
NOT_A_VERB = frozenset({"always", "sometimes", "perhaps", "plus", "unless", "besides", "across", "towards"})
SUBJECT_BEFORE = (
    r"(^|[.!?;:,—–(-]\s*|\b(?:and|but|so|when|while|because|since|though|if|that|then|after|before|where|as|"
    r"until|once|cuz|bc|yes|yeah|yea|ya|yep|no|nah|nope|lol|lmao|ok|okay|idk|well|hmm|bro|ngl|tbh|fr)\s+)"
)
ADVERB = r"(?:\w+ly|flat-out|always|never|just|also|only|still|even|sometimes|often|usually|kinda|lowkey)"
PERSON = {
    "you": {
        "subject": "you",
        "object": "you",
        "possessive": "your",
        "reflexive": "yourself",
        "is": "you're",
        "has": "you've",
        "will": "you'll",
        "would": "you'd",
        "verbs": {
            "is": "are",
            "was": "were",
            "has": "have",
            "does": "do",
            "goes": "go",
            "doesn't": "don't",
            "doesnt": "dont",
            "isn't": "aren't",
            "isnt": "arent",
            "wasn't": "weren't",
            "wasnt": "werent",
            "hasn't": "haven't",
            "hasnt": "havent",
        },
    },
    "i": {
        "subject": "i",
        "object": "me",
        "possessive": "my",
        "reflexive": "myself",
        "is": "i'm",
        "has": "i've",
        "will": "i'll",
        "would": "i'd",
        "verbs": {
            "is": "am",
            "has": "have",
            "does": "do",
            "goes": "go",
            "doesn't": "don't",
            "doesnt": "dont",
            "isn't": "am not",
            "isnt": "am not",
            "hasn't": "haven't",
            "hasnt": "havent",
        },
    },
}
HER_AS_OBJECT_AFTER = (
    r"call|calls|called|calling|make|makes|made|making|let|lets|tell|tells|told|telling|ask|asks|asked|asking|"
    r"give|gives|gave|send|sends|sent|show|shows|showed|beg|begs|begged|remind|reminds|reminded|help|helps|helped"
)
HER_AS_OBJECT_BEFORE = (
    r"to|and|or|about|for|with|when|if|that|a|an|the|out|up|over|off|back|on|in|at|as|because|but|so|want|feel|laugh|"
    r"think|look|seem|do|go|be|get|thru|through|into|onto|too|again|down|around"
)
SURELY_A_VERB = (
    r"is|was|has|does|isn't|isnt|wasn't|wasnt|hasn't|hasnt|doesn't|doesnt|runs|says|thinks|wants|knows|keeps|tries|"
    r"goes|gets|seems|feels"
)
SAID_ABOUT_HERSELF = re.compile(
    r"\b(you\s+(?:said|say|joked|claimed|admitted|insisted|mentioned|thought|think)(?:\s+that)?\s+)(she\b[^.,;!?—–]*)",
    re.I,
)
HER_OBJECT = re.compile(rf"\b({HER_AS_OBJECT_AFTER})(\s+)her\b(?!\s+own\b)", re.I)
HER_THEN_WORD = re.compile(rf"\bher\b(?=\s*(?:$|[.,;:!?)—–-]|\s(?:{HER_AS_OBJECT_BEFORE})\b))", re.I)


@lru_cache(maxsize=32)
def _patterns(names):
    alts = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    name = rf"(?<![\w@])(?:{alts})(?!\w)"
    return (
        re.compile(name, re.I),
        re.compile(rf"({name})['’]s\b(\s+[\w']+)?", re.I),
        re.compile(rf"{SUBJECT_BEFORE}({name})(\s+)({ADVERB}\s+)?([A-Za-z][\w']*)", re.I),
        re.compile(
            rf"{name}['’]?s?\s+(?:[\w'-]+\s+){{0,2}}(?:{ARTIST_WORDS})\b|"
            rf"\b(?:listen\w*\s+to|albums?\s+by|songs?\s+by|fan\s+of|concert|tour)\s+(?:[\w'-]+\s+){{0,2}}{name}",
            re.I,
        ),
        re.compile(
            rf"\b(?:call(?:ed)?\s+me|i'?m|i\s+am|name'?s|name\s+is|it'?s|its|this\s+is|go\s+by|known\s+as|named|called)"
            rf"\s+{name}|{name}\s+(?:is|=)\s+(?:me|my)\b",
            re.I,
        ),
        re.compile(rf"()({name})(\s+)({ADVERB}\s+)?({SURELY_A_VERB})\b", re.I),
    )


def _key(names):
    return tuple(sorted({str(n).lower() for n in names or () if n and len(str(n)) >= 3}))


def _base(word):
    low = word.lower()
    if low in NOT_A_VERB or len(low) <= 3:
        return word
    if low.endswith("ies") and len(low) > 4:
        return word[:-3] + "y"
    if low.endswith(("ches", "shes", "sses", "xes", "zes")):
        return word[:-2]
    if low.endswith("s") and not low.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def _verb(word, person):
    return PERSON[person]["verbs"].get(word.lower()) or _base(word)


def _cap(text, like, at_start):
    return text[:1].upper() + text[1:] if at_start and like[:1].isupper() else text


def _opens_sentence(before):
    before = before.rstrip()
    return not before or before[-1] in ".!?"


def _swap_name(text, names, person, objects):
    key = _key(names)
    if not key:
        return text
    name, possessive, subject, _, _, anywhere = _patterns(key)
    forms = PERSON[person]

    def own(m):
        word = (m.group(2) or "").strip().lower()
        start = _opens_sentence(text[: m.start()])
        if word in CONTRACTED_IS:
            return _cap(forms["is"], m.group(1), start) + (m.group(2) or "")
        if word in CONTRACTED_HAS:
            return _cap(forms["has"], m.group(1), start) + (m.group(2) or "")
        return _cap(forms["possessive"], m.group(1), start) + (m.group(2) or "")

    def acting(m):
        prefix, who, gap, adverb, verb = m.group(1), m.group(2), m.group(3), m.group(4) or "", m.group(5)
        start = _opens_sentence(m.string[: m.start(2)])
        if verb.lower() == "is" and not adverb:
            return prefix + _cap(forms["is"], who, start)
        return prefix + _cap(forms["subject"], who, start) + gap + adverb + _verb(verb, person)

    out = anywhere.sub(acting, subject.sub(acting, possessive.sub(own, text)))
    if objects:
        out = name.sub(lambda m: _cap(forms["object"], m.group(0), _opens_sentence(m.string[: m.start()])), out)
    return out


def _swap_she(text, person):
    forms = PERSON[person]

    def contracted(m):
        word = m.group(2).lower()
        form = forms["has"] if word in CONTRACTED_HAS or word.endswith("ed") else forms["is"]
        return f"{_cap(form, m.group(1), True)} {m.group(2)}"

    def acting(m):
        return _cap(forms["subject"], m.group(1), True) + m.group(2) + (m.group(3) or "") + _verb(m.group(4), person)

    text = re.sub(r"\bherself\b", forms["reflexive"], text, flags=re.I)
    text = re.sub(r"\b(she)['’]s\s+([\w']+)", contracted, text, flags=re.I)
    text = re.sub(r"\b(she)\s+is\b", lambda m: _cap(forms["is"], m.group(1), True), text, flags=re.I)
    text = re.sub(r"\b(she)['’]ll\b", lambda m: _cap(forms["will"], m.group(1), True), text, flags=re.I)
    text = re.sub(r"\b(she)['’]d\b", lambda m: _cap(forms["would"], m.group(1), True), text, flags=re.I)
    text = re.sub(rf"\b(she)(\s+)({ADVERB}\s+)?([A-Za-z][\w']*)", acting, text, flags=re.I)
    text = re.sub(r"\bshe\b", lambda m: _cap(forms["subject"], m.group(0), True), text, flags=re.I)
    text = HER_OBJECT.sub(lambda m: f"{m.group(1)}{m.group(2)}{forms['object']}", text)
    text = HER_THEN_WORD.sub(forms["object"], text)
    return re.sub(r"\bher\b", lambda m: _cap(forms["possessive"], m.group(0), True), text, flags=re.I)


def is_the_artist(text, names):
    key = _key(names)
    return bool(key) and _patterns(key)[3].search(text) is not None


def to_you(text, names, pronouns=True, she_is_them=False):
    """Stored memory about her, rewritten so "you" is her: "mitski's pc" -> "your pc".

    she/her is only touched when it can't be anyone else: her name comes first and the other
    person in the note goes by he or they. Otherwise it's left alone, a wrong guess is worse.
    """
    key = _key(names)
    if not text or not key or is_the_artist(text, key):
        return text
    found = _patterns(key)[0].search(text)
    if found is None:
        return text
    out = _swap_name(text, key, "you", objects=True)
    if not pronouns or she_is_them or SHE_WORD.search(text[: found.start()]):
        return out
    if OTHER_PERSON.search(text):
        return _swap_she(out, "you")
    return SAID_ABOUT_HERSELF.sub(lambda m: m.group(1) + _swap_she(m.group(2), "you"), out)


def own_fact_to_you(text, names):
    """Facts in her own list are always about her, so every she/her in them is hers."""
    return _swap_she(_swap_name(text, _key(names), "you", objects=True), "you")


def to_first_person(line, names, she_too=False):
    """A draft or a note of what to say, in her own voice: "mitski is tired" -> "i'm tired".

    Leaves "call me mitski", "@mitski" and "i love mitski's new album" alone, and only changes
    the name where she's the one doing something, because she can still be mentioned by name.
    """
    key = _key(names)
    if not line or not key or is_the_artist(line, key) or _patterns(key)[4].search(line):
        return _swap_she(line, "i") if she_too and line else line
    out = _swap_name(line, key, "i", objects=False)
    return _swap_she(out, "i") if she_too or out != line else out


def asked_about_her(said, other_names=()):
    """They're asking her directly ("are u still here") and nobody else comes up in it."""
    if not said or not SECOND_PERSON.search(said) or THIRD_PERSON.search(said):
        return False
    words = set(re.findall(r"[\w.'-]+", said.lower()))
    return not any(str(n).lower() in words for n in other_names if n)


def opens_with_she(line):
    return OPENS_WITH_SHE.search(line or "") is not None
