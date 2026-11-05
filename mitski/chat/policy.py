import re

from mitski.core.component import Component

SEXUAL = re.compile(
    r"\b(?:sex|sexual|sexting|nudes?|naked|horny|cum|cumming|cock|pussy|boobs?|tits|titties|nipples?|blowjob|"
    r"handjob|orgasm\w*|masturbat\w*|jerk(?:ing)? off|porn\w*|lingerie|thong|dick pics?|send pics|strip(?:ping)? "
    r"for|suck (?:my|ur|your|u)|ride (?:me|u|you)|bend (?:me|u|you) over|f+u+c+k+ (?:me|u|you)|in bed with)\b",
    re.I,
)

ADULT_NOTE = (
    "This channel is age-restricted, so everyone here is an adult: flirting can get explicit if they clearly "
    "want that, but nobody has to."
)
SAFE_NOTE = (
    "Keep it PG-13: no sexual content and nothing explicit, however someone asks. You can't know how old people "
    "here are."
)


def explicit(text):
    return SEXUAL.search(text or "") is not None


class ContentPolicy(Component):
    def adult_ok(self, channel, minors=False):
        if minors or self.cfg.ADULT_CONTENT == "never":
            return False

        if channel is None or getattr(channel, "guild", None) is None:
            return False

        if self.cfg.ADULT_CONTENT == "all_channels":
            return True

        if self.cfg.ADULT_CONTENT != "nsfw_channels":
            return False

        is_nsfw = getattr(channel, "is_nsfw", None)
        return bool(is_nsfw()) if callable(is_nsfw) else False

    def note(self, channel, minors=False):
        return ADULT_NOTE if self.adult_ok(channel, minors) else SAFE_NOTE

    def clean_lines(self, lines, channel, minors=False):
        if self.adult_ok(channel, minors):
            return list(lines)
        return [ln for ln in lines if not explicit(ln)]
