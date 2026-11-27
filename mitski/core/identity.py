import re

from mitski.core.texts import say, wording

FEMALE = {"girl", "woman", "female", "f", "she", "her"}
MALE = {"guy", "boy", "man", "male", "m", "he", "him", "dude"}
COUNTRIES = {
    "portugal": ("portugal", "portuguese", "tuga"),
    "spain": ("spain", "spanish"),
    "brazil": ("brazil", "brasil", "brazilian"),
    "france": ("france", "french"),
    "germany": ("germany", "german"),
    "italy": ("italy", "italian"),
    "uk": ("uk", "england", "english", "britain", "british", "scotland", "scottish", "wales", "welsh"),
    "ireland": ("ireland", "irish"),
    "usa": ("usa", "america", "american", "the us", "the states"),
    "canada": ("canada", "canadian"),
    "mexico": ("mexico", "mexican"),
    "netherlands": ("netherlands", "holland", "dutch"),
    "belgium": ("belgium", "belgian"),
    "poland": ("poland", "polish"),
    "sweden": ("sweden", "swedish"),
    "norway": ("norway", "norwegian"),
    "denmark": ("denmark", "danish"),
    "finland": ("finland", "finnish"),
    "russia": ("russia", "russian"),
    "ukraine": ("ukraine", "ukrainian"),
    "turkey": ("turkey", "turkish"),
    "greece": ("greece", "greek"),
    "romania": ("romania", "romanian"),
    "austria": ("austria", "austrian"),
    "switzerland": ("switzerland", "swiss"),
    "czechia": ("czechia", "czech"),
    "hungary": ("hungary", "hungarian"),
    "india": ("india", "indian"),
    "china": ("china", "chinese"),
    "japan": ("japan", "japanese"),
    "korea": ("korea", "korean"),
    "philippines": ("philippines", "filipino", "filipina"),
    "australia": ("australia", "australian", "aussie"),
    "argentina": ("argentina", "argentinian", "argentine"),
    "chile": ("chile", "chilean"),
    "colombia": ("colombia", "colombian"),
    "morocco": ("morocco", "moroccan"),
    "egypt": ("egypt", "egyptian"),
    "indonesia": ("indonesia", "indonesian"),
    "vietnam": ("vietnam", "vietnamese"),
    "thailand": ("thailand", "thai"),
    "nigeria": ("nigeria", "nigerian"),
}
WORD_TO_COUNTRY = {w: c for c, words in COUNTRIES.items() for w in words}
NATION = "|".join(sorted((re.escape(w) for w in WORD_TO_COUNTRY), key=len, reverse=True))
ME = r"(?:i'?m|im|i am)"
NOT_ABOUT_ME = (
    r"(?!\s+(?:fries|toast|food|kiss\w*|class|exam|test|homework|lesson|music|style|braid|press|cuisine|team))"
)
FROM = re.compile(rf"\b(?:{ME}\s+(?:originally\s+)?from|i come from|i (?:live|grew up) in)\s+({NATION})\b", re.I)
FACT_START = (
    (re.compile(r"^(?:is|was)\b", re.I), "i'm"),
    (re.compile(r"^lives\b", re.I), "i live"),
    (re.compile(r"^comes\b", re.I), "i come"),
    (re.compile(r"^grew\b", re.I), "i grew"),
    (re.compile(r"^turned\b", re.I), "i turned"),
)
NATIONALITY = re.compile(rf"\b{ME}\s+(?:half\s+)?({NATION})\b{NOT_ABOUT_ME}", re.I)
AGE = re.compile(
    rf"\b(?:{ME}|i turned|i just turned|turning|i'?ll be|ill be)\s+(?:only\s+|just\s+|literally\s+|actually\s+)?"
    r"(\d{1,2})(?:\s*(?:yo|y/o|yrs?(?:\s+old)?|years?(?:\s+old)?))?"
    r"(?=\s*(?:$|[!?.,)~]|\b(?:btw|lol|lmao|rn|now|too|tho|haha|and|but|so|actually|already|yo|y/o|years?|yrs?)\b))",
    re.I,
)
AGE_WORDS = re.compile(r"\b(\d{1,2})\s*(?:yo|y/o|years?\s+old)\b", re.I)
MALE_SELF = re.compile(
    rf"\b(?:{ME}\s+(?:a\s+)?(?:guy|dude|boy|man|male|dad|father|husband|boyfriend|bf)\b|as a (?:guy|man|dude|boy)\b)",
    re.I,
)
FEMALE_SELF = re.compile(
    rf"\b(?:{ME}\s+(?:a\s+)?(?:girl|woman|female|mom|mother|wife|girlfriend|gf)\b|as a (?:girl|woman)\b)", re.I
)


class Identity:
    def __init__(self, cfg):
        self.age = int(cfg.HER_AGE or 0)
        gender = str(cfg.HER_GENDER or "").strip().lower()
        self.gender = gender
        self.female = gender in FEMALE
        self.male = gender in MALE
        self.home = str(cfg.HER_FROM or "").strip()
        self.city = str(cfg.HER_CITY or "").strip()
        self.country = WORD_TO_COUNTRY.get(self.home.lower(), self.home.lower())

    @property
    def set(self):
        return bool(self.age or self.gender or self.home or self.city)

    def line(self):
        if not self.set:
            return ""
        bits = []
        if self.age:
            bits.append(f"you're {self.age}")
        if self.gender:
            bits.append(f"a {self.gender}")
        if self.home:
            bits.append(f"from {self.home}")
        if self.city:
            bits.append(say("persona.living_in", city=self.city))
        return (wording("persona.facts") + " ") + ", ".join(bits) + wording("persona.facts_end")

    def fix(self):
        return say("persona.fix_identity", line=self.line())

    def wrong_fact(self, text):
        text = str(text or "").strip()
        for pattern, start in FACT_START:
            text = pattern.sub(start, text, count=1)
        return self.wrong(text)

    def wrong(self, text):
        text = text or ""
        if self.age:
            for m in list(AGE.finditer(text)) + list(AGE_WORDS.finditer(text)):
                n = int(m.group(1))
                if 10 <= n <= 60 and n != self.age:
                    return f"says she's {n}"
        if self.female and MALE_SELF.search(text):
            return "says she's male"
        if self.male and FEMALE_SELF.search(text):
            return "says she's female"
        if self.country:
            for pattern in (FROM, NATIONALITY):
                m = pattern.search(text)
                if m and WORD_TO_COUNTRY.get(m.group(1).lower(), self.country) != self.country:
                    return f"says she's from {m.group(1)}"
        return None
