import re
from dataclasses import dataclass
from urllib.parse import urlparse

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".avif", ".heic")
VIDEO_EXT = (".mp4", ".mov", ".webm", ".mkv", ".m4v")
SAFE_HOSTS = (
    "cdn.discordapp.com",
    "media.discordapp.net",
    "images-ext-1.discordapp.net",
    "images-ext-2.discordapp.net",
    "giphy.com",
    "media.tenor.com",
    "c.tenor.com",
    "i.imgur.com",
    "pbs.twimg.com",
)
GIF_LINK = re.compile(
    r"https?://(?:www\.)?(?:tenor\.com/\S*view/\S+|giphy\.com/(?:gifs|stickers)/\S+|media\d?\.giphy\.com/\S+|"
    r"i\.giphy\.com/\S+)",
    re.I,
)
SCREENSHOT_NAME = re.compile(r"screen ?shot|screen_?cap|snip")


@dataclass(slots=True)
class Item:
    kind: str
    key: str
    source: tuple | None = None
    size: int = 0
    spoiler: bool = False
    hint: str = ""
    name: str = ""
    fmt: str = ""
    url: str = ""

    @property
    def viewable(self):
        return self.source is not None and not (self.kind == "sticker" and self.fmt == "lottie")


def gif_title(url):
    m = re.search(r"tenor\.com/(?:[\w-]+/)?view/([\w-]+?)-gif-\d+", url or "", re.I)
    if not m:
        m = re.search(r"giphy\.com/(?:gifs|stickers)/(?:[\w-]+/)?([\w-]+)-[A-Za-z0-9]{6,}(?:$|[/?#])", url or "", re.I)
    if not m:
        return ""
    return " ".join([w for w in m.group(1).split("-") if w and not w.isdigit()][:8])


def safe_url(url):
    try:
        u = urlparse(url)
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    return u.scheme == "https" and any(host == h or host.endswith("." + h) for h in SAFE_HOSTS)


def _url_key(url):
    return "u" + re.sub(r"[?#].*$", "", url or "")[-120:]


def _sticker_format(sticker):
    return str(getattr(sticker, "format", "")).lower().split(".")[-1]


def sticker_item(sticker):
    return Item("sticker", f"s{sticker.id}", ("sticker", sticker), name=sticker.name, fmt=_sticker_format(sticker))


def _attachment(a):
    ct = (a.content_type or "").lower()
    fn = (a.filename or "").lower()
    spoiler = a.is_spoiler() if hasattr(a, "is_spoiler") else fn.startswith("spoiler_")
    if ct.startswith("image/") or fn.endswith(IMAGE_EXT):
        kind = "gif" if ct == "image/gif" or fn.endswith(".gif") else "image"
        if kind == "image" and SCREENSHOT_NAME.search(fn):
            kind = "screenshot"
        return Item(kind, f"a{a.id}", ("attachment", a), a.size or 0, spoiler)
    if ct.startswith("video/") or fn.endswith(VIDEO_EXT):
        return Item("video", f"a{a.id}", ("attachment", a), a.size or 0, spoiler)
    return None


def _media_url(media):
    return getattr(media, "proxy_url", None) or getattr(media, "url", None)


def _embed(e, can_decode_video):
    kind = getattr(e, "type", "")
    if kind not in ("gifv", "image"):
        return None
    page = e.url or ""
    thumb, image, video = _media_url(e.thumbnail), _media_url(e.image), _media_url(e.video)
    title = gif_title(page)
    is_gif = kind == "gifv" or bool(title) or ".gif" in (page + str(thumb)).lower()
    src = next((u for u in (image, thumb) if u and ".gif" in u.lower()), None)
    if src is None and video and can_decode_video:
        src = video
    src = src or image or thumb or (page if page.lower().split("?")[0].endswith(IMAGE_EXT) else None)
    return Item(
        "gif" if is_gif else "image", _url_key(page or src), ("url", src) if src else None, hint=title, url=page
    )


def find_items(m, limit, can_decode_video):
    found = [_attachment(a) for a in getattr(m, "attachments", None) or []]
    found += [sticker_item(s) for s in (getattr(m, "stickers", None) or [])[:1]]
    found += [_embed(e, can_decode_video) for e in getattr(m, "embeds", None) or []]
    found = [it for it in found if it is not None]
    if not found:
        found = [
            Item("gif", _url_key(link), hint=gif_title(link), url=link) for link in GIF_LINK.findall(m.content or "")
        ]
    out, seen = [], set()
    for it in found:
        if it.key not in seen and len(out) < limit:
            seen.add(it.key)
            out.append(it)
    return out
