import re

POSITIVE = re.compile(
    r"\b(ty|thx|thanks|thank you|love|ily|cute|pretty|sweet|nice|best|queen|goated|<3)\b|❤|🥰|😊|💕|🥺", re.I
)
NEGATIVE = re.compile(r"\b(stfu|shut up|stupid|dumb|idiot|ugly|annoying|hate you|loser|cringe|trash|bitch)\b", re.I)
SNOWFLAKE = re.compile(r"(?<!\d)\d{15,21}(?!\d)")


def cut(text, limit):
    text = str(text or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def squash(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def snowflakes(text):
    return list(dict.fromkeys(int(x) for x in SNOWFLAKE.findall(text or "")))
