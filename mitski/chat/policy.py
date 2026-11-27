import re

from mitski.core import logs
from mitski.core.component import Component
from mitski.core.storage import JsonFile
from mitski.core.texts import wording

log = logs.get("policy")

SAFE, NORMAL, UNRESTRICTED = "safe", "normal", "unrestricted"
MODES = (SAFE, NORMAL, UNRESTRICTED)
ABOUT_MODES = {
    SAFE: "nice and normal, pg-13: no swearing, nothing sexual, no flirting, threats, insults or roasting",
    NORMAL: "how she usually is",
    UNRESTRICTED: "no limits on language, crude or dark humour or harsh roasts",
}

SEXUAL = re.compile(
    r"\b(?:sex|sexual|sexting|nudes?|naked|horny|cum|cumming|cock|pussy|boobs?|tits|titties|nipples?|blowjob|"
    r"handjob|orgasm\w*|masturbat\w*|jerk(?:ing)? off|porn\w*|lingerie|thong|dick pics?|send pics|strip(?:ping)? "
    r"for|suck (?:my|ur|your|u)|ride (?:me|u|you)|bend (?:me|u|you) over|f+u+c+k+ (?:me|u|you)|in bed with)\b",
    re.I,
)
MINOR_MENTION = re.compile(
    r"(?<![\d.])1[0-7]\s*(?:y/?o|yrs?|years?(?:\s+old)?)\b|"
    r"\b(?:minors?|underage|under\s*18|child(?:ren)?|kids?|teen(?:ager)?s?|schoolgirls?|schoolboys?|little (?:girl|boy)s?|"
    r"loli|shota)\b",
    re.I,
)
VULGAR = re.compile(
    r"\b(?:f+u+c*k+\w*|fk|fck\w*|motherf\w*|wtf|stfu|lmfao|af|s+h+i+t+\w*|bullshit|b+i+t+c+h+\w*|ass|asses|asshole\w*|"
    r"dumbass\w*|jackass\w*|badass\w*|smartass\w*|dick\w*|cunt\w*|bastard\w*|whore\w*|slut\w*|piss\w*|wank\w*|twat\w*|"
    r"prick\w*|n+[i1]+g+[ae3]+r*\w*|f[a4]g+\w*|retard\w*|tranny|kike|chink|spic|caralho|foda\w*|merda|puta\w*|cona|"
    r"fdp|crl|pqp|nsfw|gore)\b",
    re.I,
)
THREAT = re.compile(
    r"\b(?:kys|k+i+l+\s+(?:you|u|ya|yourself|urself|him|her|them)|murder (?:you|u|ya)|"
    r"(?:i'?ll|ill|ima|imma|i'?m gonna|im gonna|gonna|i will|about to|finna)\s+(?:\w+\s+)?"
    r"(?:find|hurt|stab|shoot|beat|murder|kill|end|destroy|punch|slap|choke|strangle|bite)\s+(?:you|u|ya|ur|your|him|her|them)|"
    r"(?:ur|you'?re|youre) dead|coming for (?:you|u|ya)|go die|drop dead|hope (?:you|u) die|watch (?:your|ur) back|"
    r"i know where (?:you|u) live)\b",
    re.I,
)
FLIRT = re.compile(
    r"\b(?:babe|baby|bby|cutie|sexy|hottie|daddy|mommy|thicc|kiss(?:es)? (?:me|u|you)|cuddle (?:me|u|you|with)|"
    r"marry me|be my (?:gf|bf|girlfriend|boyfriend)|wanna date|go on a date|(?:i )?love (?:you|u|ya)|ily|"
    r"(?:ur|you'?re|youre) (?:so |really |kinda )?(?:hot|cute|fine|pretty)|handsome|gorgeous|sweetheart|darling|hubby|"
    r"wifey|mwah|seduc\w*|naughty)\b|[😘😍🥰😏🥵💋👅🍆🍑💦🫦😈🖕]",
    re.I,
)
BULLY = re.compile(
    r"\b(?:loser|idiot|moron|dummy|noob|clown|shut up|nobody likes (?:you|u)|hate (?:you|u)|skill issue|"
    r"(?:you|u|ur|you'?re|youre|ya)\b[^.!?\n]{0,25}\b(?:stupid|dumb|trash|garbage|pathetic|ugly|fat|worthless|annoying|"
    r"cringe|bad at)\b|roast(?:ed|ing)?)\b",
    re.I,
)
TONE = (("vulgar", VULGAR), ("a threat", THREAT), ("flirting", FLIRT), ("bullying", BULLY))
UNTAMED = re.compile(r"flirt|chemistry|roast|threat|sarcas|insult|rude|savage|bully|explicit|sexy|horny", re.I)
STAYS = re.compile(r"\bminor\b|age-appropriate", re.I)

ADULT_NOTE = wording("safety.adult_channel")
PG13_NOTE = wording("safety.pg13")
SAFE_NOTE = PG13_NOTE
SAFE_SERVER_NOTE = wording("safety.safe_server")
SAFE_REMINDER = wording("safety.safe_reminder")
UNRESTRICTED_NOTE = wording("safety.unrestricted_server")
ALWAYS_NOTE = wording("safety.hard_limits")
MINOR_HERE_NOTE = wording("safety.minor_here")
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}
REVIEW_SYSTEM = wording("safety.review_system")
GIF_RATINGS = ("g", "pg", "pg-13", "r")


def explicit(text):
    return SEXUAL.search(text or "") is not None


def sexualizes_a_minor(text):
    return explicit(text) and MINOR_MENTION.search(text or "") is not None


def tone_problem(text):
    for name, pattern in TONE:
        if pattern.search(text or ""):
            return name
    return None


def tame(text):
    parts = re.split(r"(?<=[.!?])\s+", text or "")
    return " ".join(p for p in parts if STAYS.search(p) or not UNTAMED.search(p))


class ContentPolicy(Component):
    def __init__(self, app):
        super().__init__(app)
        self.file = JsonFile(app.cfg.paths.data_file("server_modes.json"))
        self.modes = {}

    def load(self):
        saved = self.file.load()
        self.modes = {int(g): m for g, m in saved.items() if str(g).isdigit() and m in MODES}

    def set_mode(self, guild_id, mode):
        if mode == SAFE:
            self.modes.pop(guild_id, None)
        else:
            self.modes[guild_id] = mode
        self.file.save({str(g): m for g, m in self.modes.items()})
        log.info("server %s is now %s", guild_id, mode)

    def mode_in(self, guild):
        return None if guild is None else self.modes.get(guild.id, SAFE)

    def mode(self, channel):
        return self.mode_in(getattr(channel, "guild", None))

    def adult_ok(self, channel, minors=False):
        if minors or self.cfg.ADULT_CONTENT == "never":
            return False

        if channel is None or getattr(channel, "guild", None) is None:
            return False

        if self.mode(channel) == SAFE:
            return False

        if self.cfg.ADULT_CONTENT == "all_channels":
            return True

        if self.cfg.ADULT_CONTENT != "nsfw_channels":
            return False

        is_nsfw = getattr(channel, "is_nsfw", None)
        return bool(is_nsfw()) if callable(is_nsfw) else False

    def note(self, channel, minors=False):
        mode = self.mode(channel)
        if mode == SAFE:
            return SAFE_SERVER_NOTE
        if minors:
            return f"{MINOR_HERE_NOTE} {PG13_NOTE}"
        sexual = ADULT_NOTE if self.adult_ok(channel) else PG13_NOTE
        return f"{UNRESTRICTED_NOTE} {sexual} {ALWAYS_NOTE}" if mode == UNRESTRICTED else sexual

    def reminder(self, channel):
        return SAFE_REMINDER if self.mode(channel) == SAFE else ""

    def tamed(self, channel, text):
        return tame(text) if self.mode(channel) == SAFE else text

    def breaks(self, text, channel, minors=False):
        if sexualizes_a_minor(text):
            return "sexual and about a minor"
        if explicit(text) and not self.adult_ok(channel, minors):
            return "explicit"
        if minors and FLIRT.search(text or ""):
            return "flirting with a minor"
        return tone_problem(text) if self.mode(channel) == SAFE else None

    def clean_lines(self, lines, channel, minors=False):
        return [ln for ln in lines if not self.breaks(ln, channel, minors)]

    def fits(self, guild, text):
        return self.mode_in(guild) != SAFE or tone_problem(text) is None

    def minors_here(self, channel):
        recent = [uid for _, uid in list(self.state.chan_log.get(channel.id, ()))[-30:]]
        return self.app.ages.any_minor(recent)

    def gif_rating(self, channel):
        rating = str(self.cfg.GIF_RATING or "pg-13").lower()
        if self.mode(channel) == SAFE or self.minors_here(channel):
            return min((rating, "pg-13"), key=lambda r: GIF_RATINGS.index(r) if r in GIF_RATINGS else 2)
        return rating

    async def judged_unsafe(self, lines, channel):
        if self.mode(channel) != SAFE or not self.cfg.SAFETY_REVIEW or not lines:
            return False
        verdict = await self.app.helper.ask_json(REVIEW_SYSTEM, "\n".join(lines), REVIEW_SCHEMA, 20)
        return bool(verdict) and verdict.get("ok") is False
