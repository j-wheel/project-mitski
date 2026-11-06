import re

from mitski.chat.patterns import (
    ANY_URL,
    CHANNEL_MENTION,
    EVERYONE_MENTION,
    ROBOTIC,
    ROLE_MENTION,
    STICKER_TAG,
    USER_MENTION,
)
from mitski.chat.policy import explicit
from mitski.core import voice
from mitski.core.component import Component
from mitski.core.metrics import Metrics

AT_NAME = re.compile(r"(?<![\w@])@[A-Za-z][\w.]{1,31}")
FILE_NAME = re.compile(r"\b[\w-]+\.(?:mp4|mov|webm|mkv|png|jpe?g|gif|webp|mp3|wav|ogg)\b", re.I)
SPEAKER_PREFIX = re.compile(r"^\s*(?:assistant|user|bot)\s*:\s+", re.I)
ECHO_WORDS = 4
MEDIA_TAG = re.compile(
    r"\[(?:youtube video|video|link|gif|image|screenshot|sticker|file|attachment|audio)\b[^\]]*\]", re.I
)


def _norm(text):
    return re.sub(r"[^\w]+", " ", text.lower()).strip()


class DraftFilter(Component):
    def tidy(self, text, channel_id, others=()):
        text = self.llm.fmt.clean(text)
        said_before = {s.lower() for s in self.state.recent_said[channel_id]}
        keep_at = {str(n).lower() for n in others}
        other_prefix = None
        if others:
            other_prefix = re.compile(
                r"^\s*(" + "|".join(re.escape(n) for n in others) + r")\s*(?:\([^)]{0,60}\))?\s*:\s", re.I
            )
        own = self.messages.own_names()
        own_prefix = None
        if own:
            own_prefix = re.compile(
                r"^\s*(?:" + "|".join(re.escape(n) for n in own) + r")\s*(?:\([^)]{0,60}\))?\s*:\s+", re.I
            )
        lines = []
        for line in text.split("\n"):
            if other_prefix and other_prefix.match(line):
                break
            stickers = [f"[sticker: {s.strip()}]" for s in STICKER_TAG.findall(line)]
            line = STICKER_TAG.sub("", line)
            line = MEDIA_TAG.sub("", line)
            line = ANY_URL.sub("", line)
            line = USER_MENTION.sub("", line)
            line = ROLE_MENTION.sub("", line)
            line = CHANNEL_MENTION.sub("", line)
            line = EVERYONE_MENTION.sub("", line)
            line = AT_NAME.sub(lambda m: m.group(0) if m.group(0)[1:].rstrip(".").lower() in keep_at else "", line)
            line = FILE_NAME.sub("", line)
            line = SPEAKER_PREFIX.sub("", line)
            if own_prefix:
                line = own_prefix.sub("", line)
            line = re.sub(r"^\s*\((?:replying|reply|answering) to [^)]{0,60}\)\s*:?\s*", "", line, flags=re.I)
            line = re.sub(r"[ \t]+", " ", line).strip()
            line = re.sub(r"^(?:[,;]\s*|:\s+)(?=\w)", "", line)
            line = self._own_voice(line, own)
            if self.cfg.STRIP_PERIODS and line.endswith(".") and not line.endswith(".."):
                line = line[:-1].rstrip()
            for piece in [line] + stickers[:1]:
                if not piece or piece in {",", ";", "-", "*", '"', "'"}:
                    continue
                if lines and lines[-1].lower() == piece.lower():
                    continue
                if piece.lower() in said_before:
                    continue
                lines.append(piece[:1900])
        return lines[: self.cfg.MAX_LINES]

    @staticmethod
    def _own_voice(line, own):
        fixed = voice.to_first_person(line, own)
        if fixed != line:
            Metrics.event("third person fixed")
        return fixed

    def echoed(self, lines, msgs):
        theirs = list(dict.fromkeys(self.messages.text(m) for m in list(msgs) if m.author.id != self.me.id))[-40:]
        whole = {_norm(t) for t in theirs} | {_norm(line) for t in theirs for line in t.split("\n")}
        blob = " " + " ".join(_norm(t) for t in theirs) + " "
        return [ln for ln in lines if len(_norm(ln)) >= 8 and (_norm(ln) in whole or f" {_norm(ln)} " in blob)]

    def problem(self, lines, msgs, honest=False, adult=True, direct=False):
        if any(ROBOTIC.search(ln) for ln in lines):
            return "robotic"
        if not adult and any(explicit(ln) for ln in lines):
            return "explicit"
        if direct and any(voice.opens_with_she(ln) for ln in lines):
            return "third person"
        copied = self.echoed(lines, msgs)
        total = sum(len(ln) for ln in lines) or 1
        if (
            len(copied) >= 2
            or sum(len(ln) for ln in copied) >= 0.5 * total
            or any(len(_norm(ln).split()) >= ECHO_WORDS for ln in copied)
        ):
            return "echo"
        return None
