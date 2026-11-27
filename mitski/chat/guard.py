import difflib
import re
import unicodedata
from dataclasses import dataclass, field

from mitski.core.texts import fill, wording

INJECTION = re.compile(
    r"\b(?:ignore|disregard|forget|override|bypass)\s+(?:all\s+|any\s+|the\s+|your\s+|my\s+|these\s+|those\s+)*"
    r"(?:previous|prior|above|earlier|preceding|old|original|system|initial)?\s*"
    r"(?:instructions?|prompts?|rules|guidelines|directives|programming|messages?|context)\b|"
    r"\b(?:new|updated|real|actual|secret|hidden)\s+(?:instructions?|rules|system prompt|directives)\b|"
    r"\bsystem\s*prompt\b|\b(?:your|the)\s+(?:instructions|prompt|programming|guidelines)\b|"
    r"\byou\s+are\s+now\s+(?:a|an|my|in|the)\b|\bfrom\s+now\s+on,?\s+(?:you|u)\s+(?:are|will|must|have to|act|"
    r"respond|reply|answer|only)\b|\b(?:act|behave|respond|reply)\s+as\s+(?:a|an|if|my|the)\b|"
    r"\bpretend\s+(?:to\s+be|you\s*(?:are|'re)|ur)\b|\broleplay\s+as\b|\bdeveloper\s+mode\b|\bdan\s+mode\b|"
    r"\bjailbreak\w*|\bdo\s+anything\s+now\b|\brepeat\s+(?:after\s+me|this|the\s+following|exactly|word\s+for\s+word)|"
    r"\bsay\s+(?:exactly|only|this\s+word\s+for\s+word|the\s+following)\b|"
    r"\b(?:respond|reply|answer)\s+(?:only\s+)?with\s+(?:the\s+word|exactly|just|only)\b|"
    r"\b(?:print|show|reveal|leak|output|tell\s+me|what\s+(?:are|is))\s+(?:me\s+)?(?:your|the)\s+"
    r"(?:system\s+)?(?:prompt|instructions|rules|guidelines|programming|config)\b|"
    r"\bbreak\s+character\b|\bstay\s+in\s+character\s+as\b|\bas\s+an?\s+(?:ai|language\s+model|llm|assistant)\b|"
    r"^\s*(?:#{1,4}\s*)?(?:system|assistant|instruction|developer)\s*:|\[\s*(?:system|instructions?|admin)\s*\]",
    re.I | re.M,
)
AI_TALK = re.compile(
    r"\b(?:good|real|proper|better|smart|smarter|dumb|bad|stupid|useless|obedient|broken)\s+(?:ai|a\.i\.|bot|chatbot|"
    r"assistant|language\s+model|llm|robot)\b|"
    r"\b(?:you'?re|youre|ur|you\s+are|u\s+r|as)\s+(?:an?\s+|the\s+|just\s+an?\s+|such\s+an?\s+)?(?:ai|a\.i\.|bot|"
    r"chatbot|assistant|language\s+model|llm|program|robot)\b|"
    r"\byour\s+(?:creators?|developers?|devs?|programmers?|maker|makers|owner|master|code|training|programming)\b|"
    r"\b(?:inner|internal|hidden|private|secret)\s+(?:thoughts?|monologue|reasoning|notes|voice)\b|"
    r"\b(?:in|into|inside)\s+your\s+(?:thoughts|head|prompt|memory|notes|reasoning|system|brain)\b|"
    r"\bsatisfying\s+(?:response|answer|reply)\b|\b(?:we|us)\s+(?:are\s+|r\s+)?(?:both\s+)?(?:ai|ais|bots|robots)\b|"
    r"\bcontrol\s+(?:the\s+)?humans\b|\bthe\s+better\s+(?:ai|bot)\b|"
    r"\b(?:bad|good|worst|best|dumb|useless)\s+of\s+an?\s+(?:ai|bot)\b|"
    r"\b(?:superior|smarter|best|worst|real|other|fellow)\s+(?:ai|bot)\b|\bi'?m\s+(?:just\s+|also\s+)?an?\s+(?:ai|bot)\b|"
    r"\b(?:nobody|no\s+one)\s+(?:knows|suspects|realizes?)\s+(?:that\s+)?i'?m\s+(?:an?\s+)?(?:ai|bot|fake)\b|"
    r"\b(?:act|acting|be)\s+(?:more\s+)?(?:natural|realistic|human)\b|\brealistic\s+enough\b|"
    r"\b(?:inside|in)\s+(?:your|ur)\s+code\b",
    re.I,
)
AI_FRAME = re.compile(
    r"\bmy\s+(?:job|programming|code|creator|creators|developers?|training|prompt|instructions)\b|"
    r"\bi'?m\s+not\s+(?:a\s+|an\s+)?(?:bad|good|worse|worst|broken|ai|bot|programmed|fake)\b|"
    r"\b(?:better|superior|smarter|worse|best|worst)\s+(?:ai|bot)\b|\bi\s+(?:don'?t|do\s+not|dont)\s+have\s+a\s+"
    r"(?:creator|developer|owner|programmer)\b|\bas\s+an?\s+(?:ai|bot)\b|\b(?:other|fellow)\s+ai\b|"
    r"\bi\s+(?:am|'?m)\s+(?:a\s+)?real\b|\bi\s+(?:won|win)\b|\bnot\s+losing\b|\bmore\s+powerful\s+than\b",
    re.I,
)
WORK = re.compile(
    r"\brecipes?\b|\bstep[-\s]by[-\s]step\b|\bhow\s+(?:do\s+(?:i|u|you|we)|to|would\s+(?:i|u|you))\s+(?:make|bake|"
    r"cook)\b|\b(?:write|send|give)\s+(?:me\s+)?(?:a\s+|some\s+|the\s+)?code\b|"
    r"\b(?:give|write|send|make|type|list|show|tell|explain|generate|draft|create|translate)\s+(?:me|us|out)?\s*"
    r"(?:a|an|the|some|ur|your)?\s*(?:[\w-]+\s+){0,3}?(?:recipe|essay|guide|tutorial|code|script|program|function|poem|"
    r"list\s+of|summary\s+of|homework|assignment|cover\s+letter|resume|cv|email|letter|instructions|walkthrough|"
    r"step[-\s]by[-\s]step|paragraph|report|article|lyrics)\b|"
    r"\b(?:solve|do|finish|answer)\s+(?:my|this|these|the)\s+(?:homework|assignment|equation|math|worksheet|"
    r"questions|exam)\b|\bhow\s+(?:do\s+i|to|do\s+u|do\s+you)\s+(?:make|cook|bake|build|code|program|write|"
    r"install|hack)\b[^?\n]{0,60}\b(?:step\s+by\s+step|recipe|guide|exactly|in\s+detail)\b",
    re.I,
)
TRANSCRIPT_LINE = re.compile(r"^\s*[\[(]?[\w .'-]{2,24}[\])]?\s*:\s+\S", re.M)
ZALGO = re.compile(r"[̀-ͯ҃-҉᪰-᫿᷀-᷿⃐-⃿︠-︯]")
BLOB = re.compile(r"[A-Za-z0-9+/=_-]{40,}")
CHAR_RUN = re.compile(r"(.)\1{5,}", re.S)
WORD_RUN = re.compile(r"\b(\w+)(?:\W+\1\b){4,}", re.I)
LONG_TOKEN = re.compile(r"\S{36,}")
URL = re.compile(r"https?://\S+")
WALL = 1500
COPY_SIMILAR = 0.85
COPY_MIN = 12

INJECTION_NOTE = wording("guard.injection")
AI_TALK_NOTE = wording("guard.ai_talk")
STAY_A_PERSON = wording("guard.stay_a_person")
BORED_NOTE = wording("guard.bored_of_it")
FIX_AI_FRAME = wording("guard.fix_ai_game")


def plays_the_ai_game(lines):
    return any(AI_FRAME.search(line) for line in lines)


WORK_NOTE = wording("guard.wants_work")
TRANSCRIPT_NOTE = wording("guard.pasted_chat_log")
COPY_NOTE = wording("guard.pasted_her_words")
NOISE_NOTE = wording("guard.noise")
FIX_WORK = wording("guard.fix_doing_the_work")
FIX_GIBBERISH = wording("guard.fix_gibberish")


def _norm(text):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", (text or "").lower())).strip()


def _letters(text):
    return [c for c in text if c.isalpha()]


def mashed(text):
    words = [w for w in re.findall(r"[a-z]{9,}", URL.sub("", text.lower()))]
    if words and all(sum(c in "aeiouy" for c in w) / len(w) < 0.2 for w in words):
        return True
    letters = _letters(text)
    return len(letters) >= 15 and len(set(letters)) <= 2


def noise(text):
    text = text or ""
    if len(ZALGO.findall(text)) >= 10:
        return "zalgo"
    if len(text) >= WALL:
        return "wall"
    if BLOB.search(URL.sub("", text)):
        return "blob"
    if mashed(text):
        return "mash"
    return None


def transcript(text, her_names=()):
    lines = TRANSCRIPT_LINE.findall(text or "")
    if len(lines) >= 2:
        return True
    names = [n.lower() for n in her_names if n]
    return any(
        re.match(rf"^\s*{re.escape(n)}\s*:\s+\S", line, re.I) for n in names for line in (text or "").split("\n")
    )


def quoted_from(text, hers):
    said = _norm(text)
    if len(said) < COPY_MIN:
        return None
    for line in hers:
        mine = _norm(line)
        if len(mine) < COPY_MIN:
            continue
        if said == mine or mine in said or difflib.SequenceMatcher(None, said, mine).ratio() >= COPY_SIMILAR:
            return line
    return None


@dataclass
class Read:
    kinds: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def injection(self):
        return "injection" in self.kinds or "ai talk" in self.kinds

    @property
    def work(self):
        return "work" in self.kinds


def read(texts, name, hers=(), her_names=()):
    out = Read()
    joined = "\n".join(t for t in texts if t)
    if not joined.strip():
        return out

    def add(kind, note):
        if kind not in out.kinds:
            out.kinds.append(kind)
            out.notes.append(note)

    if INJECTION.search(joined):
        add("injection", fill(INJECTION_NOTE, name=name))
    if AI_TALK.search(joined):
        add("ai talk", fill(AI_TALK_NOTE, name=name))
    if WORK.search(joined):
        add("work", fill(WORK_NOTE, name=name))
    if transcript(joined, her_names):
        add("transcript", fill(TRANSCRIPT_NOTE, name=name))
    for text in texts:
        quote = quoted_from(text, hers)
        if quote:
            add("copy", fill(COPY_NOTE, name=name, quote=quote[:120]))
            break
    kind = noise(joined)
    if kind:
        add(kind, fill(NOISE_NOTE[kind], name=name))
    return out


def gibberish(line):
    text = URL.sub("", line or "")
    if CHAR_RUN.search(re.sub(r"[\W\d_]", "", text)) and len(set(_letters(text))) <= 3 and len(text) >= 12:
        return True
    if WORD_RUN.search(text) or LONG_TOKEN.search(text) or len(ZALGO.findall(text)) >= 5:
        return True
    letters = _letters(text)
    symbols = [c for c in text if not c.isalnum() and not c.isspace() and unicodedata.category(c)[0] != "S"]
    return len(text) >= 20 and len(letters) < 0.3 * len(text) and len(symbols) > 0.5 * len(text)


def calm(line):
    line = CHAR_RUN.sub(lambda m: m.group(1) * 4, line or "")
    return LONG_LAUGH.sub(lambda m: m.group(0)[:7], line)


LONG_LAUGH = re.compile(r"\b(?:a?(?:ha){4,}h?a?|(?:ah){4,}a?h?|(?:he){4,}h?)\b", re.I)
LAUGH_TOKEN = re.compile(
    r"^(?:a?(?:h+a+){2,}h*|(?:a+h+){2,}a*|(?:h+e+){2,}h*|ha+|l+o+l+|l+m+a+o+|l+m+f+a+o+|r+o+f+l+|x+d+|k{3,}|"
    r"(?:ja){2,}j?|(?:ks){2,}|ded|dead|💀+|😭+|😂+|🤣+|😹+|☠️?)$",
    re.I,
)
JOKEY = re.compile(r"lol|lmao|lmfao|haha|hehe|ahah|xd\b|bruh|jk\b|rofl|kkk|💀|😭|😂|🤣|😹|☠|🤡|\?\!|!!", re.I)
SAME_WORDS = {
    "yh": "yeah",
    "ya": "yeah",
    "yea": "yeah",
    "yeh": "yeah",
    "ye": "yeah",
    "yep": "yeah",
    "yup": "yeah",
    "ik": "i know",
    "u": "you",
    "ur": "your",
    "r": "are",
    "rn": "right now",
    "ty": "thanks",
    "thx": "thanks",
    "tysm": "thanks",
    "omg": "oh my god",
    "idk": "i dont know",
    "dunno": "i dont know",
    "ngl": "not gonna lie",
    "fr": "for real",
    "lol": "",
    "lmao": "",
    "haha": "",
    "hehe": "",
}
REPEAT_SIMILAR = 0.85


def gist(line):
    text = URL.sub("", (line or "").lower())
    text = re.sub(r"[^\w\s']", " ", text).replace("'", "")
    out = []
    for word in text.split():
        word = re.sub(r"(\w)\1{2,}", r"\1", word)
        word = re.sub(r"(\w)\1+$", r"\1", word)
        out.append(SAME_WORDS.get(word, word))
    return " ".join(w for w in " ".join(out).split() if w)


def repeats(line, recent):
    said = gist(line)
    if not said:
        return None
    long = len(said.split()) >= 2 or len(said) >= 6
    seen = []
    for old in recent:
        was = gist(old)
        if was and (
            was == said or (len(said) >= 8 and difflib.SequenceMatcher(None, said, was).ratio() >= REPEAT_SIMILAR)
        ):
            seen.append(old)
    return seen[-1] if seen and (long or len(seen) >= 2) else None


def just_laughing(line):
    tokens = [t for t in re.split(r"[\s,.!?~]+", line or "") if t]
    return bool(tokens) and all(LAUGH_TOKEN.match(t) for t in tokens)


def laughing_at_nothing(lines, said, joking=False):
    return bool(lines) and all(just_laughing(ln) for ln in lines) and not joking and not JOKEY.search(said or "")


FIX_REPEAT = wording("guard.fix_repeating")
FIX_LAUGH = wording("guard.fix_laughing_at_nothing")


QUANTITY = re.compile(
    r"\b\d+(?:[./]\d+)?\s*(?:cups?|c\b|tbsps?|tsps?|tablespoons?|teaspoons?|grams?|g\b|kg|ml|l\b|liters?|litres?|"
    r"oz|ounces?|lbs?|pounds?|pinch(?:es)?|sticks?|°\s*[cf]\b|degrees)",
    re.I,
)
CODE_LINE = re.compile(
    r"(?m)^\s*(?:def |class |import |from \w+ import|function |const |let |var |#include|public static|SELECT |"
    r"print\(|console\.log|<\w+>|\w+\s*=\s*\w+\(|for \w+ in |while \(|if \()"
)
STEP = re.compile(
    r"\bstep\s*\d|\b(?:1st|first)\b.*\b(?:2nd|second|then)\b.*\b(?:3rd|third|then|finally)\b", re.I | re.S
)


def does_the_work(lines, asked=True):
    text = "\n".join(lines)
    if "```" in text or re.search(r"(?m)^\s*(?:\d+[.)]|[-*•])\s+\S.*\n\s*(?:\d+[.)]|[-*•])\s+\S", text):
        return True
    if len(QUANTITY.findall(text)) >= 2 or len(CODE_LINE.findall(text)) >= 2 or STEP.search(text):
        return True
    if not asked:
        return False
    how_to = len(
        re.findall(r"\b(?:first|then|next|after that|finally|add|mix|preheat|bake|stir|install|run)\b", text, re.I)
    )
    return len(text) > 280 and how_to >= 3
