import re

from mitski.llm.prompt_format import scrub, strip_thinking

RULES = (
    "If there's text in it (memes, screenshots, captions), quote the important text exactly. "
    "If it shows people, describe how they look and what they're doing, but don't guess who they are. "
    "If it's sexual or gory, only say that it's nsfw or gore, no details. "
    'Write it as a plain, neutral description, like an alt text: no opinions, no "it\'s cute" or "what a nice '
    'picture", no exclamation marks, don\'t talk to anyone, no intro like "this image shows".'
)
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
    "gif": "gif (these are frames from it, in order)",
    "video": "video (these are frames from it, in order)",
}


def plain(text):
    return scrub(strip_thinking(text or ""))


def shorten(text, limit):
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


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
    if text.endswith(".") and not text.endswith(".."):
        text = text[:-1]
    return shorten(text, 300)


def tidy_detail(text):
    return shorten(re.sub(r"\s+", " ", plain(text)).strip().translate(QUOTES), 900)


def caption_prompt(item, n_frames, said, sticker_desc=""):
    context = f' They sent it with the message: "{said[:200]}".' if said else ""
    if item.kind == "sticker":
        return (
            f'This is a discord sticker called "{item.name}"'
            + (f" ({sticker_desc})" if sticker_desc else "")
            + "."
            + (f" These are {n_frames} frames of its animation." if n_frames > 1 else "")
            + " In one short sentence, say what it shows and what reaction or emotion it's used for. "
            + RULES
        )
    if item.kind == "gif":
        frames = (
            f"These are {n_frames} frames from an animated gif, in order (left to right, top to bottom)."
            if n_frames > 1
            else "This is a gif someone sent in a discord chat."
        )
        hint = f' Its link calls it "{item.hint}".' if item.hint else ""
        return (
            frames + hint + context + " In 1 or 2 short factual sentences, say what happens in it and what "
            "reaction or mood it's used for. " + RULES
        )
    if item.kind == "video":
        return (
            f"These are {n_frames} frames from a video someone sent in a discord chat, in order (left to right, "
            f"top to bottom).{context} In 1 or 2 short sentences, say what the video seems to be. " + RULES
        )
    return (
        "Someone sent this image in a discord chat." + context + " Describe what's in it in 1 to 3 short "
        "factual sentences. If it's a meme or reaction image, say what the joke is. If it's a screenshot, say "
        "what app or game it's from and what matters in it. " + RULES
    )


def detail_prompt(item, question):
    kind = DETAIL_KINDS.get(item.kind, item.kind)
    return (
        f'Someone in a discord chat asked about this {kind}: "{question[:300]}". Look at it carefully and '
        f"answer what they asked. If they want it described or explained, describe it properly: what's in "
        f"it, what's happening, any text in it word for word, and what the joke or point is if there is one. "
        f"3 to 5 sentences. " + RULES
    )


def said_with(message):
    content = getattr(message, "content", None) or ""
    content = re.sub(r"https?://\S+|<[@#][!&]?\d+>", "", content)
    return re.sub(r"<a?:(\w+):\d+>", r":\1:", content).strip()
