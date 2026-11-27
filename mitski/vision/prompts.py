import re

from mitski.core.texts import say, wording
from mitski.llm.prompt_format import scrub, strip_thinking

RULES = wording("media.image_rules")
CHATTY = re.compile(
    r"\bvibes?\b|\b(?:cute|adorable|wholesome|lovely|cheerful|beautiful|nice|fun|happy|sweet)\s*,?\s*"
    r"(?:\w+\s+)?(?:picture|photo|image|shot|pic|moment|selfie)\b|^(?:it'?s|what) (?:just )?an? "
    r"(?:\w+,?\s+){0,3}(?:picture|photo|image|pic)\b|\b(?:love|adore) (?:this|it)\b",
    re.I,
)
INTRO = re.compile(
    r"^\s*(?:the |this )?(?:image|picture|photo|gif|sticker|frames?|video)s?\s+(?:shows?|depicts?|features?)\s*:?\s*",
    re.I,
)
QUOTES = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "[": "(", "]": ")"})
DETAIL_KINDS = {
    "screenshot": "screenshot",
    "gif": wording("media.kind_gif"),
    "video": wording("media.kind_video"),
}


def plain(text):
    return scrub(strip_thinking(text or ""))


CAPTION_MAX = 700
DETAIL_MAX = 1800


def shorten(text, limit):

    if len(text) <= limit:
        return text
    head = text[:limit]
    ends = [m.end() for m in re.finditer(r"[.!?](?=\s|$)", head)]
    if ends and ends[-1] >= limit // 3:
        return head[: ends[-1]].strip()
    return head[: limit - 1].rsplit(" ", 1)[0] + "…"


def _drop_chatty(sentence):
    if not CHATTY.search(sentence):
        return sentence
    parts = [p for p in re.split(r",\s*(?:and|but|so|while)\s+", sentence) if not CHATTY.search(p)]
    return ", ".join(parts).rstrip(".") + "." if parts else None


def tidy_caption(text):
    text = INTRO.sub("", plain(text).strip()).translate(QUOTES)
    kept = [s for s in (_drop_chatty(x) for x in re.split(r"(?<=[.!?])\s+", text.strip())) if s]
    text = " ".join(kept) if kept else text
    text = re.sub(r"!+", ".", text)
    text = re.sub(r"\s+", " ", text).strip().strip("\"'")
    text = shorten(text, CAPTION_MAX)
    if text.endswith(".") and not text.endswith(".."):
        text = text[:-1]
    return text


def tidy_detail(text):
    return shorten(re.sub(r"\s+", " ", plain(text)).strip().translate(QUOTES), DETAIL_MAX)


def caption_prompt(item, n_frames, said, sticker_desc=""):
    context = (" " + say("media.sent_with", message=said[:200])) if said else ""
    if item.kind == "sticker":
        return (
            say("media.sticker_called", name=item.name)
            + (f" ({sticker_desc})" if sticker_desc else "")
            + "."
            + ((" " + say("media.sticker_frames", n_frames=n_frames)) if n_frames > 1 else "")
            + (" " + wording("media.sticker_describe") + " ")
            + RULES
        )
    if item.kind == "gif":
        frames = say("media.gif_frames", n_frames=n_frames) if n_frames > 1 else wording("media.gif")
        hint = (" " + say("media.gif_link", hint=item.hint)) if item.hint else ""
        return frames + hint + context + (" " + wording("media.gif_describe") + " ") + RULES
    if item.kind == "video":
        return (say("media.video", n_frames=n_frames, context=context) + " ") + RULES
    return wording("media.image") + context + (" " + wording("media.image_describe") + " ") + RULES


def detail_prompt(item, question):
    kind = DETAIL_KINDS.get(item.kind, item.kind)
    return (say("media.look_closer", kind=kind, question=question[:300]) + " ") + RULES


def said_with(message):
    content = getattr(message, "content", None) or ""
    content = re.sub(r"https?://\S+|<[@#][!&]?\d+>", "", content)
    return re.sub(r"<a?:(\w+):\d+>", r":\1:", content).strip()
