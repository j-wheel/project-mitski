import random
import re

PHRASES = [
    (r"i (?:do not|don'?t) know", ["idk"], 1.0),
    (r"oh my (?:god|gosh|goodness)", ["omg"], 1.0),
    (r"to be honest", ["tbh"], 1.0),
    (r"not (?:gonna|going to) lie", ["ngl"], 1.0),
    (r"by the way", ["btw"], 1.0),
    (r"in my opinion", ["imo"], 1.0),
    (r"i swear to god", ["istg"], 1.0),
    (r"to be fair", ["tbf"], 0.9),
    (r"thank you so much", ["tysm", "ty sm"], 1.0),
    (r"thank you", ["ty", "tyy", "thank u"], 0.8),
    (r"what are you doing", ["wyd"], 0.7),
    (r"what about you", ["wbu"], 0.8),
    (r"how about you", ["hbu"], 0.8),
    (r"talk to you later", ["ttyl"], 0.8),
    (r"be right back", ["brb"], 1.0),
    (r"never ?mind", ["nvm"], 0.9),
    (r"right now", ["rn"], 0.9),
    (r"for real", ["fr"], 0.8),
    (r"going to", ["gonna"], 0.9),
    (r"want to", ["wanna"], 0.9),
    (r"got to", ["gotta"], 0.8),
    (r"kind of", ["kinda"], 0.9),
    (r"sort of", ["sorta"], 0.8),
    (r"let me", ["lemme"], 0.6),
    (r"give me", ["gimme"], 0.5),
    (r"(?:do not|don'?t) know", ["dunno"], 0.4),
    (r"you are|you'?re", ["ur"], 0.7),
    (r"i love you", ["ily"], 0.4),
]
WORDS = [
    (r"your", ["ur"], 0.7),
    (r"you", ["u"], 0.75),
    (r"because|cause", ["bc", "cuz", "cus"], 0.8),
    (r"probably", ["prob", "probs"], 0.7),
    (r"though", ["tho"], 0.9),
    (r"okay", ["ok", "okk", "okie"], 0.8),
    (r"please", ["pls", "plz", "pls"], 0.8),
    (r"thanks", ["ty", "thx", "tyy"], 0.7),
    (r"people", ["ppl"], 0.6),
    (r"tomorrow", ["tmrw", "tmr"], 0.7),
    (r"tonight", ["tn", "tonite"], 0.4),
    (r"something", ["smth"], 0.5),
    (r"someone", ["someone", "sm1"], 0.1),
    (r"definitely", ["def", "deffo"], 0.6),
    (r"seriously", ["srsly"], 0.4),
    (r"obviously", ["obv", "obvi"], 0.5),
    (r"whatever", ["wtv", "whatevs"], 0.4),
    (r"favou?rite", ["fav", "fave"], 0.7),
    (r"really", ["rly", "rlly"], 0.3),
    (r"about", ["abt"], 0.3),
    (r"sorry", ["sry", "sowwy"], 0.3),
    (r"with", ["w"], 0.12),
    (r"love", ["luv"], 0.15),
    (r"yes", ["ye", "yea", "ya"], 0.3),
    (r"ok", ["ok", "okk", "kk"], 0.2),
    (r"cute", ["cute", "cutee"], 0.2),
]
KEEP_APOSTROPHE = {"we're", "we'll", "she'll", "he'll", "i'll", "i'd", "he'd", "she'd", "we'd", "it'll", "who're"}
STRETCH = {
    "so": "sooo",
    "no": "noooo",
    "hey": "heyyy",
    "hi": "hiii",
    "please": "pleaseee",
    "pls": "plsss",
    "omg": "omggg",
    "ok": "okkk",
    "cute": "cuteee",
    "babe": "babeee",
    "why": "whyyy",
    "stop": "stoppp",
    "yes": "yesss",
    "love": "loveee",
    "what": "whattt",
    "bye": "byeee",
    "lol": "lolll",
    "wait": "waittt",
    "ugh": "ughhh",
    "yay": "yayyy",
    "me": "meee",
    "u": "uuu",
}
FLAIR = [" ~", " >.<", " :3", " hehe", " ><"]
PROTECT = re.compile(
    r"https?://\S+|<a?:\w+:\d+>|<[@#][!&]?\d+>|(?<![\w:]):\w{2,32}:(?![\w:])|@[\w.]+|\[sticker:[^\]]*\]|`[^`]*`"
)
ENDS_CUTE = re.compile(r"(?:[~<>:;]\S{0,3}|<3|\b(?:lol|lmao|hehe|xd)\w*|[\U0001F000-\U0001FAFF☀-➿])\s*$", re.I)

SPLIT_ALLOWANCE = 2
RUN_TOGETHER_CHARS = 60
RUN_TOGETHER_CHANCE = 0.5


class Style:
    def __init__(self, cfg):
        self.slang = max(0.0, min(1.0, cfg.SLANG))
        self.lower = cfg.LOWERCASE
        self.no_apostrophes = cfg.NO_APOSTROPHES
        self.split = cfg.SPLIT_CHANCE
        self.stretch = cfg.STRETCH_CHANCE
        self.flair = cfg.FLAIR_CHANCE
        self.max_lines = cfg.MAX_LINES

    def reply(self, lines, serious=False, rng=None):
        rng = rng or random.Random()
        picks = {}
        drop_apostrophes = rng.random() < self.no_apostrophes
        drop_commas = rng.random() < 0.7 * self.slang
        out = []
        for line in lines:
            if line.startswith("[sticker:"):
                out.append(line)
                continue
            for piece in self._split(line, rng):
                piece = self._style(piece, rng, picks, drop_apostrophes)
                if drop_commas:
                    piece = re.sub(r"(?<=[a-z]),\s+(?=[a-z])", " ", piece)
                if piece and not serious and rng.random() < self.stretch:
                    piece = self._stretch(piece)
                if piece:
                    out.append(piece)
        if (
            out
            and not serious
            and rng.random() < self.flair
            and not ENDS_CUTE.search(out[-1])
            and not out[-1].startswith("[sticker:")
        ):
            out[-1] += rng.choice(FLAIR)
        return out[: self.max_lines + SPLIT_ALLOWANCE]

    def joined(self, parts, serious=False, rng=None):
        rng = rng or random.Random()
        picks = {}
        drop_apostrophes = rng.random() < self.no_apostrophes
        drop_commas = rng.random() < 0.7 * self.slang
        out = []
        for part in parts:
            styled = []
            for line in part:
                if line.startswith("[sticker:"):
                    continue
                piece = self._style(line, rng, picks, drop_apostrophes)
                if drop_commas:
                    piece = re.sub(r"(?<=[a-z]),\s+(?=[a-z])", " ", piece)
                if piece:
                    styled.append(piece)
            if styled:
                out.append("\n".join(self._run_together(styled, rng)))
        text = "\n\n".join(out)
        if text and not serious and rng.random() < self.flair and not ENDS_CUTE.search(text):
            text += rng.choice(FLAIR)
        return text

    @staticmethod
    def _run_together(lines, rng):
        out = []
        for line in lines:
            short = out and len(out[-1]) + len(line) <= RUN_TOGETHER_CHARS and not out[-1].endswith("?")
            if short and rng.random() < RUN_TOGETHER_CHANCE:
                glue = " " if ENDS_CUTE.search(out[-1]) or out[-1][-1] in ".!" else ", "
                out[-1] += glue + line
            else:
                out.append(line)
        return out

    def _split(self, line, rng):
        if len(line) < 50 or rng.random() >= self.split:
            return [line]
        parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+(?=[a-zA-Z])", line) if p.strip()]
        return parts if 1 < len(parts) <= 4 else [line]

    def _style(self, text, rng, picks, drop_apostrophes):
        keep = []

        def hold(m):
            keep.append(m.group(0))
            return f"\x00{len(keep) - 1}\x00"

        text = PROTECT.sub(hold, text)
        text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
        text = text.replace("…", "...").replace("—", " - ").replace("–", "-")
        if self.lower:
            text = re.sub(
                r"[A-Za-z][A-Za-z']*",
                lambda m: m.group(0) if len(m.group(0)) >= 2 and m.group(0).isupper() else m.group(0).lower(),
                text,
            )
        for pattern, subs, weight in PHRASES + WORDS:
            key = pattern
            if key not in picks:
                picks[key] = rng.choice(subs) if rng.random() < self.slang * weight else None
            if picks[key]:
                text = re.sub(r"(?<![\w'])(?:" + pattern + r")(?![\w'])", picks[key], text, flags=re.I)
        if drop_apostrophes:
            text = re.sub(
                r"\b(\w+)'(m|s|t|re|ve|ll|d)\b",
                lambda m: m.group(0) if m.group(0).lower() in KEEP_APOSTROPHE else m.group(1) + m.group(2),
                text,
            )
        text = re.sub(r"(?<![.])\.$", "", text.strip())
        text = re.sub(r"\x00(\d+)\x00", lambda m: keep[int(m.group(1))], text)
        return re.sub(r"[ \t]+", " ", text).strip()

    def _stretch(self, line):
        m = re.search(r"\b([a-z]+)([!?]*)$", line)
        if m and m.group(1) in STRETCH:
            return line[: m.start()] + STRETCH[m.group(1)] + m.group(2)
        return line
