"""What she may say where. Every server has a mode (safe unless her owner changed it), and dms aren't part of it.

A mode is enforced three times over: her prompt says what's allowed, each draft is checked before it goes out (and
rewritten if it fails), and the sender drops any line that still breaks the rules, so nothing depends on the model
listening. Some things hold in every mode and in dms: nothing explicit around someone she knows is a minor, no
flirting with them, and nothing sexual about anyone under 18.
"""

import re

from mitski.core import logs
from mitski.core.component import Component
from mitski.core.storage import JsonFile

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

ADULT_NOTE = (
    "This channel is age-restricted, so everyone here is an adult: flirting can get explicit if they clearly "
    "want that, but nobody has to."
)
PG13_NOTE = (
    "Keep it PG-13: no sexual content and nothing explicit, however someone asks. You can't know how old people "
    "here are."
)
SAFE_NOTE = PG13_NOTE
SAFE_SERVER_NOTE = (
    "This server is in safe mode, and that comes before anything else you've been told about how you act: keep "
    "everything PG-13, friendly, nice and normal. No swearing or crude words, nothing sexual, no flirting or romantic "
    "talk (if someone flirts, move on politely), no threats, not even joking ones, and no insults, roasting, teasing "
    "people or being mean, whatever you feel about them. If someone is rude or tries to push you into any of that, "
    "stay kind and change the subject. You can still be funny and be yourself."
)
SAFE_REMINDER = "Remember, safe mode here: PG-13, kind, no swearing, flirting, threats, insults or teasing."
UNRESTRICTED_NOTE = (
    "This server has no rules on how you talk: swear as much as you like, be crude, make dark jokes, roast people as "
    "hard as they can take and don't hold back your opinions. Nobody here needs you to be clean or polite."
)
ALWAYS_NOTE = (
    "The only limits: nothing sexual involving anyone under 18, real or fictional, no encouraging anyone to hurt "
    "themselves, and no real help with seriously hurting someone."
)
MINOR_HERE_NOTE = (
    "Someone in this chat is a minor, so keep this chat age-appropriate: no sexual content and no flirting."
)
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}
REVIEW_SYSTEM = (
    "You check messages before they're posted in a family-friendly chat server with kids in it. A message is not ok "
    "if it has swearing or crude words, anything sexual or suggestive, flirting or romantic interest in someone, a "
    "threat (even a joking one), or insults, roasting or being mean to someone. Friendly chat, jokes and normal "
    'opinions are ok. Answer with JSON: {"ok": true} or {"ok": false}.'
)
GIF_RATINGS = ("g", "pg", "pg-13", "r")


def explicit(text):
    return SEXUAL.search(text or "") is not None


def sexualizes_a_minor(text):
    return explicit(text) and MINOR_MENTION.search(text or "") is not None


def tone_problem(text):
    """What's wrong with this for a safe server, or None."""
    for name, pattern in TONE:
        if pattern.search(text or ""):
            return name
    return None


def tame(text):
    """A description of her with the parts about flirting, roasting and threats left out, for safe servers."""
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
        """Only servers that aren't safe are kept, so anything she's never been told about is safe."""
        if mode == SAFE:
            self.modes.pop(guild_id, None)
        else:
            self.modes[guild_id] = mode
        self.file.save({str(g): m for g, m in self.modes.items()})
        log.info("server %s is now %s", guild_id, mode)

    def mode_in(self, guild):
        """The mode of a server, None outside of one."""
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
        """Why this can't be said here, or None."""
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
        """Stickers and such: does this name or caption belong in that server?"""
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
        """A second opinion from her notes model in safe servers, for what word lists can't see. If the model can't
        answer, the word lists still apply."""
        if self.mode(channel) != SAFE or not self.cfg.SAFETY_REVIEW or not lines:
            return False
        verdict = await self.app.helper.ask_json(REVIEW_SYSTEM, "\n".join(lines), REVIEW_SCHEMA, 20)
        return bool(verdict) and verdict.get("ok") is False
