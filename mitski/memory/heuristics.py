import re

from mitski.llm import prompt_format
from mitski.memory.schema import CAT_ALIASES, CATEGORIES, SLOT_ALIASES, SLOTS, STRENGTH

DISCLOSURE = re.compile(
    r"\b(i'?m|im|i am)\s+\d{1,2}\b|\byears? old\b|\bi\s+(just\s+)?(turned|moved|broke up|graduated|got (a|an|my)|"
    r"started|quit|lost|live|work|study|go to|have a|hate|love)\b|\bmy (name|age|birthday|bday|pronouns|bf|gf|"
    r"boyfriend|girlfriend|partner|wife|husband|mom|dad|brother|sister|dog|cat|job|school|uni|exam|fav)\b|"
    r"\bcall me\b|\bi go by\b|\bpronouns\b|\b(remember|forget) (that|this|it|me|my)\b|\bactually\b|\bnot anymore\b|"
    r"\bno longer\b|\bnot (true|right)\b|\bi'?m (from|in|not|single|taken|dating|moving)\b|"
    r"\bim (from|in|not|single|taken|dating|moving)\b",
    re.I,
)


AGE_NOW = re.compile(
    r"\b(?:i'?m|im|i am)\s+(\d{1,2})\s*(?:years?\s*old|yrs?\s*old|y/?o)\b"
    r"|\bi\s+(?:just\s+)?turned\s+(\d{1,2})\b(?!\s*(?:kills|times|wins|levels|%))"
    r"|\bmy age is\s+(\d{1,2})\b",
    re.I,
)


NAME_WORD = r"([A-Za-z][\w'\-]{1,19}(?:\s+[A-Za-z][\w'\-]{1,19})?)"


CALL_ME = re.compile(r"\b(?:(?:you|u) can |just |pls |please )?(?:call me|i go by)\s+" + NAME_WORD, re.I)


MY_NAME = re.compile(r"\b(?:my (?:real |irl )?name(?:'s| is)|i'?m called)\s+" + NAME_WORD, re.I)


DONT_CALL = re.compile(r"\b(?:don'?t|do not|dont|stop|quit) call(?:ing)? me\s+" + NAME_WORD, re.I)


HER_NICK = [
    re.compile(
        r"\b(?:i'?ll|ill|ima|imma|i'?m (?:gonna|going to)|im gonna|gonna|i'?m|im|i will) "
        r"(?:start )?call(?:ing)? (?:you|u|ya) " + NAME_WORD,
        re.I,
    ),
    re.compile(r"\bfrom now on (?:you'?re|ur|your name is|ur name is|you are|u are|ur called) " + NAME_WORD, re.I),
    re.compile(r"\b(?:your|ur) (?:new )?(?:nickname|nick|name) is (?:now )?" + NAME_WORD, re.I),
]


NOT_A_NAME = set(
    [
        "later",
        "back",
        "when",
        "whenever",
        "tomorrow",
        "tmrw",
        "tmr",
        "tonight",
        "rn",
        "now",
        "if",
        "on",
        "in",
        "at",
        "a",
        "an",
        "the",
        "not",
        "so",
        "just",
        "crazy",
        "what",
        "whatever",
        "anything",
        "that",
        "it",
        "you",
        "u",
        "out",
        "up",
        "maybe",
        "soon",
        "again",
        "sometime",
        "sometimes",
        "after",
        "before",
        "then",
        "lol",
        "lmao",
        "haha",
        "xd",
        "ok",
        "okay",
        "pls",
        "please",
        "bro",
        "dude",
        "ever",
        "too",
        "also",
        "and",
        "or",
        "but",
        "because",
        "cuz",
        "cause",
        "from",
        "by",
        "for",
        "with",
        "to",
        "of",
        "my",
        "your",
        "ur",
        "his",
        "her",
        "their",
        "this",
        "next",
        "today",
        "yesterday",
        "something",
        "someone",
        "anytime",
    ]
)


PET_NAMES = set(
    [
        "doll",
        "dolly",
        "babe",
        "baby",
        "bby",
        "bae",
        "hun",
        "hon",
        "honey",
        "sweetie",
        "sweetheart",
        "sweety",
        "cutie",
        "cutiepie",
        "darling",
        "dear",
        "dearie",
        "love",
        "luv",
        "lovely",
        "angel",
        "princess",
        "queen",
        "king",
        "girl",
        "girlie",
        "gurl",
        "sis",
        "sister",
        "bro",
        "brother",
        "bruh",
        "bud",
        "buddy",
        "dude",
        "man",
        "mate",
        "pal",
        "homie",
        "fam",
        "chief",
        "boss",
        "boo",
        "boo-boo",
        "bestie",
        "bff",
        "friend",
        "friendo",
        "kiddo",
        "kid",
        "sport",
        "champ",
        "pookie",
        "bean",
        "shawty",
        "shorty",
        "ma",
        "mommy",
        "mami",
        "daddy",
        "papi",
        "lil",
        "lil",
        "bro",
    ]
)


NON_ANSWER = re.compile(
    r"^(?:unknown|none|null|nil|n/?a|no|nope|-+|\?+|idk|not (?:mentioned|said|known|specified|given|sure)|"
    r"nothing|not stated|unspecified|same|unchanged|no change)\.?$",
    re.I,
)


CHAT_ACTION = re.compile(
    r"^(?:used|uses|said|says|sent|sends|asked|asks|typed|greeted|replied|posted|wrote|mentioned|"
    r"reacted|pinged|laughed|joked|called (?:her|you)|is (?:saying|asking|chatting|talking|greeting|"
    r"replying|typing|spamming|posting))\b",
    re.I,
)


PASSING_MOOD = re.compile(
    r"^(?:is|was|seems|seemed|feels|felt)\s+(?:(?:currently|now|right now|a bit|a little|very|really|"
    r"so|kinda|feeling|experiencing|getting|in a)\s+)*(?:heightened\s+)?(?:tired|sleepy|bored|frustrat\w*|"
    r"overwhelm\w*|annoyed|angry|mad|sad|upset|happy|excited|hungry|stressed|sick|confused|nervous|"
    r"anxious|good mood|bad mood|grumpy|hyper|sleepy|cold|hot|busy|online|offline|afk|here)\b",
    re.I,
)


def junk_fact(text, person=True):
    words = re.sub(r":\w+:|<a?:\w+:\d+>|[^\w\s']", " ", text).split()
    if len([w for w in words if re.search(r"[a-z]", w, re.I)]) < 2:
        return True
    if CHAT_ACTION.match(text):
        return True
    return person and bool(PASSING_MOOD.match(text))


FIRST_PERSON = re.compile(r"^(?:i|i'm|im|i've|ive|my|me|we)\b", re.I)


BEING_AI_OR_HUMAN = re.compile(
    r"\b(?:an?\s+)?(?:ai|bot|robot|chatbot|llm)\b|\b(?:real|actual)\s+(?:person|girl|human)\b", re.I
)


STOP = set(
    [
        "the",
        "and",
        "for",
        "you",
        "your",
        "are",
        "was",
        "were",
        "that",
        "this",
        "with",
        "have",
        "has",
        "had",
        "not",
        "but",
        "just",
        "like",
        "what",
        "when",
        "where",
        "which",
        "who",
        "how",
        "its",
        "it's",
        "i'm",
        "im",
        "dont",
        "don't",
        "they",
        "them",
        "their",
        "there",
        "then",
        "than",
        "about",
        "from",
        "into",
        "out",
        "get",
        "got",
        "can",
        "could",
        "would",
        "should",
        "will",
        "really",
        "very",
        "also",
        "too",
        "lol",
        "lmao",
        "yeah",
        "yes",
        "nah",
        "some",
        "any",
        "all",
        "one",
        "more",
        "much",
        "been",
        "being",
        "did",
        "does",
        "doing",
        "say",
        "said",
        "know",
        "think",
        "want",
        "make",
        "made",
        "thing",
        "things",
        "time",
        "she",
        "her",
        "him",
        "his",
        "they're",
        "thats",
        "that's",
        "gonna",
        "wanna",
        "kinda",
    ]
)


IDS = re.compile(r"\b([FS])\s*(\d+)\b", re.I)


def whole(text, hard):
    text = str(text or "").strip()
    if len(text) < hard - 3:
        return text
    ends = list(re.finditer(r"[.!?](?=\s|$)", text))
    if ends and ends[-1].end() > len(text) * 0.4:
        return text[: ends[-1].end()].strip()
    for sep in (", ", " - ", " — ", "; "):
        i = text.rfind(sep)
        if i > len(text) * 0.5:
            return text[:i].strip()
    return text.rsplit(" ", 1)[0].strip()


def norm_text(text):
    text = str(text or "").lower().replace("’", "'").replace("‘", "'")
    text = re.sub(r"<a?:(\w+):\d+>", r" \1 ", text)
    return re.sub(r"[^\w']+", " ", text).replace("'", "").strip()


def find_evidence(quote, lines):
    q = norm_text(quote)
    if not q:
        return None
    qw = q.split()
    for who, text in lines:
        t = norm_text(text)
        if t and (q in t or (len(qw) <= 3 and t == q)):
            return who
    if len(qw) < 4:
        return None
    best = None
    for who, text in lines:
        tw = set(norm_text(text).split())
        hit = sum(1 for w in qw if w in tw) / len(qw)
        if hit >= 0.8 and (best is None or hit > best[0]):
            best = (hit, who)
    return best[1] if best else None


def rank(src):
    return STRENGTH.index(src) if src in STRENGTH else 0


def unsure(x):
    return (x or {}).get("src") in ("guess", "heard")


def words(text):
    out = set()
    for w in re.findall(r"[a-z0-9']{3,}", text.lower()):
        w = w.strip("'")
        if len(w) < 3 or w in STOP:
            continue
        for suf in ("ing", "ed", "es", "s"):
            if len(w) > len(suf) + 2 and w.endswith(suf):
                w = w[: -len(suf)]
                break
        out.add(w)
    return out


def similar(a, b, threshold=0.6):
    wa, wb = words(a), words(b)
    if not wa or not wb:
        return a.strip().lower() == b.strip().lower()
    return len(wa & wb) / len(wa | wb) >= threshold


def clean_fact(text, name=None):
    text = prompt_format.SPECIAL.sub("", str(text or ""))
    text = text.strip().strip("\"'`").strip()
    for n in [name] if isinstance(name, str) else list(name or []):
        if n:
            text = re.sub(r"^" + re.escape(n) + r"('s)?\s+", lambda m: "their " if m.group(1) else "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).rstrip(" .;,")
    return text


def clean_name(raw):
    kept = []
    for w in str(raw or "").strip().strip("\"'.,!?").split():
        if w.lower() in NOT_A_NAME:
            break
        kept.append(w)
    name = " ".join(kept[:2]).strip("\"'.,!?")
    return name if 2 <= len(name) <= 30 else None


def norm_cat(cat):
    cat = (cat or "other").strip().lower()
    cat = CAT_ALIASES.get(cat, cat)
    return cat if cat in CATEGORIES else "other"


def norm_slot(key):
    key = key.strip().lower().replace("_", " ")
    key = SLOT_ALIASES.get(key, key).replace(" ", "_")
    return key if key in SLOTS or key == "her_nick" else None
