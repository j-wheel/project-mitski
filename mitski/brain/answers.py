import math
import re
from dataclasses import dataclass

from mitski.core import logs
from mitski.core.text import cut

log = logs.get("brain")

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
        "tell",
        "them",
        "it's",
        "said",
    ]
)

MONTHS = (
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
)

ASSISTANTY = re.compile(
    r"\b(i'?m (aware|happy|glad|sorry|an ai)|i understand|i (can|could) (help|assist)|as an ai|"
    r"feel free|let me know|happy to (chat|help)|here (for you|to help)|respond(ing)? to you|how can i|"
    r"you'?re feeling|you seem|i see that|i notice)\b",
    re.I,
)


def keywords(text):
    return {w for w in re.findall(r"[a-z0-9]{3,}", str(text).lower()) if w not in STOP}


SENTENCE_START = re.compile(r"(?:^|[.!?:;]\s+|\n|[\"'(]\s*)$")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
NUMBER = re.compile(r"\d+(?:[.:]\d+)?")
WORD = re.compile(r"[A-Za-z][\w'-]*")
THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}\b)")


@dataclass(frozen=True)
class Facts:
    strong: frozenset = frozenset()
    names: frozenset = frozenset()

    def __bool__(self):
        return bool(self.strong or self.names)


def _dated(brief, m):
    around = brief[max(0, m.start() - 4) : m.end() + 4]
    return bool(re.search(r"\d", around))


def key_facts(brief):
    brief = THOUSANDS.sub("", str(brief or ""))
    lowered = set(re.findall(r"\b[a-z][\w'-]*", brief))
    strong = set(NUMBER.findall(brief))
    names = set()
    for m in WORD.finditer(brief):
        w, low = m.group(0), m.group(0).lower()
        capital = w[0].isupper()
        if low in MONTHS or low in WEEKDAYS:
            if capital or _dated(brief, m):
                strong.add(low[:3])
        elif len(w) >= 2 and w.isupper():
            strong.add(low)
        elif (
            capital
            and len(w) >= 3
            and low not in STOP
            and low not in lowered
            and "'" not in w
            and not SENTENCE_START.search(brief[: m.start()])
        ):
            names.add(low)
    return Facts(frozenset(strong), frozenset(names))


def mentions(said, key):
    if key[0].isdigit():
        return re.search(r"(?<![\d.])" + re.escape(key) + r"(?![\d])", said) is not None
    return re.search(r"\b" + re.escape(key), said) is not None


def answers_it(lines, brief, strict=False):
    said = THOUSANDS.sub("", " ".join(lines).lower())
    if not said.strip():
        return False
    if all(ln.rstrip().endswith("?") for ln in lines):
        return False
    facts = key_facts(brief)
    if any(mentions(said, k) for k in facts.strong):
        return True
    if strict and facts.names and sum(mentions(said, k) for k in facts.names) >= math.ceil(len(facts.names) / 2):
        return True
    if facts.strong or (strict and facts.names):
        return False
    if not strict:
        return True
    key = {w for w in keywords(brief) if len(w) >= 4 or w.isdigit()}
    return not key or bool(key & keywords(said))


def clean_brief(text):
    text = cut(str(text or "").strip().strip('"'), 300)
    if not text or ASSISTANTY.search(text):
        if text:
            log.info("dropped a brief that sounded like an assistant: %r", text)
        return ""
    return text
