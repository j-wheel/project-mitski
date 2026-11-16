"""A printout of a whole dm, styled like discord's dark theme, as one pdf.

The page is built as html (so it can look like discord) and printed to pdf by a headless chrome or edge. Everything
from discord is escaped before any formatting is added, so nothing in a message can turn into markup or script.
"""

import asyncio
import html
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import discord

from mitski.core import logs

log = logs.get("printchat")

GROUP_GAP = timedelta(minutes=7)
FREE_UPLOAD = 10 * 1024 * 1024 - 64 * 1024
NITRO_UPLOAD = 50 * 1024 * 1024 - 64 * 1024
RENDER_TIMEOUT = 600
PNG_WIDTH = 860
PNG_SLICE = 12000
PNG_MEASURE_HEIGHT = 1000
PNG_MAX_HEIGHT = 1500000
BACKGROUND = (49, 51, 56)
MEASURE = (
    "<script>window.addEventListener('load',function(){document.documentElement.setAttribute('data-height',"
    "Math.ceil(document.documentElement.getBoundingClientRect().height))})</script>"
)
IMAGE_EXT = re.compile(r"\.(?:png|jpe?g|gif|webp|bmp|avif)(?:\?|$)", re.I)
VIDEO_EXT = re.compile(r"\.(?:mp4|mov|webm|mkv)(?:\?|$)", re.I)
BROWSER_NAMES = ("chrome", "msedge", "chromium", "chromium-browser", "google-chrome", "microsoft-edge")
BROWSER_PATHS = (
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)
DEFAULT_AVATAR = "https://cdn.discordapp.com/embed/avatars/0.png"


class TooTall(RuntimeError):
    pass


def find_browser(configured=""):
    if configured:
        return configured if Path(configured).exists() else None
    for name in BROWSER_NAMES:
        found = shutil.which(name)
        if found:
            return found
    for raw in BROWSER_PATHS:
        path = Path(os.path.expandvars(raw))
        if path.exists():
            return str(path)
    return None


@dataclass
class Row:
    id: int
    author_id: int
    name: str
    avatar: str
    when: object
    text: str = ""
    edited: bool = False
    reply: tuple | None = None
    attachments: list = field(default_factory=list)
    embeds: list = field(default_factory=list)
    stickers: list = field(default_factory=list)
    reactions: list = field(default_factory=list)
    system: str | None = None


def _avatar(user):
    asset = getattr(user, "display_avatar", None) or getattr(user, "avatar", None)
    return str(getattr(asset, "url", "") or DEFAULT_AVATAR)


def _name(user):
    return str(getattr(user, "display_name", None) or getattr(user, "global_name", None) or getattr(user, "name", "?"))


def rows_from(messages, tz):
    """Plain rows from discord messages, oldest first, with each reply pointing at what it replied to."""
    by_id = {m.id: m for m in messages}
    rows = []
    for m in messages:
        row = Row(
            id=m.id,
            author_id=m.author.id,
            name=_name(m.author),
            avatar=_avatar(m.author),
            when=m.created_at.astimezone(tz) if tz else m.created_at,
            text=m.content or "",
            edited=bool(getattr(m, "edited_at", None)),
        )
        if m.type not in (discord.MessageType.default, discord.MessageType.reply):
            try:
                row.system = m.system_content or str(m.type).split(".")[-1].replace("_", " ")
            except Exception:
                row.system = str(m.type).split(".")[-1].replace("_", " ")
        ref = getattr(m, "reference", None)
        if ref is not None and getattr(ref, "message_id", None):
            parent = getattr(ref, "resolved", None)
            if not hasattr(parent, "author"):
                parent = by_id.get(ref.message_id)
            if parent is not None and hasattr(parent, "author"):
                snippet = parent.content or ("[image]" if getattr(parent, "attachments", None) else "[message]")
                row.reply = (_name(parent.author), _avatar(parent.author), snippet[:120])
            else:
                row.reply = (None, None, "Original message was deleted")
        for a in getattr(m, "attachments", None) or []:
            kind = (getattr(a, "content_type", None) or "").split("/")[0]
            url = str(getattr(a, "url", ""))
            if kind == "image" or IMAGE_EXT.search(a.filename or ""):
                kind = "image"
            elif kind == "video" or VIDEO_EXT.search(a.filename or ""):
                kind = "video"
            else:
                kind = "file"
            row.attachments.append({"kind": kind, "name": a.filename, "url": url, "size": getattr(a, "size", 0)})
        for e in getattr(m, "embeds", None) or []:
            row.embeds.append(_embed(e))
        for s in getattr(m, "stickers", None) or []:
            fmt = str(getattr(s, "format", "")).lower()
            row.stickers.append({"name": s.name, "url": "" if "lottie" in fmt else str(getattr(s, "url", ""))})
        for r in getattr(m, "reactions", None) or []:
            emoji = r.emoji
            url = str(getattr(emoji, "url", "") or "") if not isinstance(emoji, str) else ""
            row.reactions.append(
                {"emoji": str(emoji) if not url else getattr(emoji, "name", ""), "url": url, "count": r.count}
            )
        rows.append(row)
    return rows


def _embed(e):
    def sub(obj, attr):
        return str(getattr(getattr(e, obj, None), attr, "") or "")

    color = getattr(e, "color", None) or getattr(e, "colour", None)
    return {
        "type": str(getattr(e, "type", "rich") or "rich"),
        "title": str(getattr(e, "title", "") or ""),
        "description": str(getattr(e, "description", "") or ""),
        "url": str(getattr(e, "url", "") or ""),
        "color": f"#{color.value:06x}" if color is not None and getattr(color, "value", None) is not None else "",
        "provider": sub("provider", "name"),
        "author": sub("author", "name"),
        "image": sub("image", "url") or sub("image", "proxy_url"),
        "thumbnail": sub("thumbnail", "url") or sub("thumbnail", "proxy_url"),
        "fields": [(str(f.name), str(f.value)) for f in getattr(e, "fields", None) or []],
    }


CUSTOM_EMOJI = re.compile(r"&lt;(a?):(\w{2,32}):(\d{15,21})&gt;")
USER_MENTION = re.compile(r"&lt;@!?(\d{15,21})&gt;")
ROLE_MENTION = re.compile(r"&lt;@&amp;(\d{15,21})&gt;")
CHANNEL_MENTION = re.compile(r"&lt;#(\d{15,21})&gt;")
LINK = re.compile(r"https?://(?:(?!&gt;|&lt;|&quot;|&#x27;)[^\s<])+")


def _link(m):
    url = m.group(0)
    tail = re.search(r"[.,:;!?)\]]+$", url)
    url, tail = (url[: tail.start()], tail.group(0)) if tail else (url, "")
    return f'<a href="{url}">{url}</a>', tail


ONLY_EMOJI = re.compile(r"^(?:\s|<a?:\w+:\d+>|[\U0001F000-\U0001FAFF☀-➿‍️])+$")


def _emoji_img(m, size):
    ext = "gif" if m.group(1) else "png"
    return (
        f'<img class="emoji" alt=":{m.group(2)}:" title=":{m.group(2)}:" '
        f'src="https://cdn.discordapp.com/emojis/{m.group(3)}.{ext}?size={size}">'
    )


def markdown(text, names, images=True):
    """Discord-style formatting for one message. text is escaped first, then formatting is added on top."""
    jumbo = bool(text) and bool(ONLY_EMOJI.match(text)) and len(text) <= 60
    out = html.escape(text or "")
    keep = []

    def hold(snippet):
        keep.append(snippet)
        return f"\x00{len(keep) - 1}\x00"

    out = re.sub(
        r"```(?:[\w+-]*\n)?(.*?)```",
        lambda m: hold(f"<pre><code>{m.group(1).strip(chr(10))}</code></pre>"),
        out,
        flags=re.S,
    )
    out = re.sub(r"`([^`\n]+)`", lambda m: hold(f"<code>{m.group(1)}</code>"), out)
    out = LINK.sub(lambda m: hold(_link(m)[0]) + _link(m)[1], out)
    out = CUSTOM_EMOJI.sub(lambda m: hold(_emoji_img(m, 96 if jumbo else 48)) if images else f":{m.group(2)}:", out)
    out = USER_MENTION.sub(
        lambda m: hold(f'<span class="mention">@{html.escape(names.get(int(m.group(1)), "user"))}</span>'), out
    )
    out = ROLE_MENTION.sub(lambda m: hold('<span class="mention">@role</span>'), out)
    out = CHANNEL_MENTION.sub(lambda m: hold('<span class="mention">#channel</span>'), out)
    out = re.sub(r"\|\|(.+?)\|\|", r'<span class="spoiler">\1</span>', out, flags=re.S)
    out = re.sub(r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>", out, flags=re.S)
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out, flags=re.S)
    out = re.sub(r"__(.+?)__", r"<u>\1</u>", out, flags=re.S)
    out = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", out, flags=re.S)
    out = re.sub(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", r"<i>\1</i>", out, flags=re.S)
    out = re.sub(r"~~(.+?)~~", r"<s>\1</s>", out, flags=re.S)
    lines = []
    for line in out.split("\n"):
        heading = re.match(r"^(#{1,3}) (.+)$", line)
        if heading:
            level = len(heading.group(1))
            line = f"<h{level + 2}>{heading.group(2)}</h{level + 2}>"
        elif line.startswith("&gt; "):
            line = f"<blockquote>{line[5:]}</blockquote>"
        lines.append(line)
    out = "<br>".join(lines).replace("</blockquote><br><blockquote>", "<br>")
    out = re.sub(r"(</h\d>|</blockquote>)<br>", r"\1", out)
    out = re.sub(r"\x00(\d+)\x00", lambda m: keep[int(m.group(1))], out)
    return out, jumbo


# ---- the page ----

CSS = """
@page { size: A4; margin: 0; }
html, body { margin: 0; background: #313338; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { color: #dbdee1; font-family: "gg sans", "Noto Sans", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
       font-size: 15px; line-height: 1.375; padding-bottom: 24px; }
a { color: #00a8fc; text-decoration: none; word-break: break-all; }
.head { padding: 28px 16px 14px 16px; border-bottom: 1px solid #3f4147; display: flex; align-items: center; }
.head img { width: 56px; height: 56px; border-radius: 50%; margin-right: 14px; }
.head h1 { font-size: 22px; color: #f2f3f5; margin: 0 0 2px 0; font-weight: 700; }
.head .sub { color: #949ba4; font-size: 13px; }
.day { display: flex; align-items: center; margin: 24px 16px 8px 16px; color: #949ba4; font-size: 12px;
       font-weight: 600; break-after: avoid; }
.day::before, .day::after { content: ""; flex: 1; border-top: 1px solid #3f4147; }
.day span { padding: 0 8px; }
.msg { position: relative; padding: 2px 48px 2px 72px; break-inside: avoid; page-break-inside: avoid; }
.msg.first { margin-top: 17px; min-height: 44px; }
.avatar { position: absolute; left: 16px; top: 4px; width: 40px; height: 40px; border-radius: 50%; }
.msg.first.replying .avatar { top: 26px; }
.header { display: flex; align-items: baseline; gap: 8px; }
.name { color: #f2f3f5; font-weight: 600; }
.name.her { color: #e9a8ff; }
.time { color: #949ba4; font-size: 12px; }
.text { white-space: normal; overflow-wrap: anywhere; }
.text.jumbo .emoji { width: 48px; height: 48px; }
.text.jumbo { font-size: 44px; line-height: 1.2; }
.edited { color: #949ba4; font-size: 10px; margin-left: 4px; }
.mention { background: rgba(88,101,242,.3); color: #c9cdfb; border-radius: 3px; padding: 0 2px; font-weight: 500; }
.emoji { width: 22px; height: 22px; vertical-align: -5px; object-fit: contain; }
code { background: #2b2d31; border: 1px solid #1e1f22; border-radius: 4px; padding: 0 3px;
       font-family: Consolas, "Courier New", monospace; font-size: 85%; }
pre { background: #2b2d31; border: 1px solid #1e1f22; border-radius: 4px; padding: 8px; margin: 4px 0;
      white-space: pre-wrap; max-width: 90%; }
pre code { background: none; border: 0; padding: 0; font-size: 13px; }
blockquote { border-left: 4px solid #4e5058; margin: 2px 0; padding: 0 0 0 12px; }
h3, h4, h5 { margin: 6px 0 2px 0; color: #f2f3f5; }
.spoiler { background: #1e1f22; border-radius: 3px; padding: 0 2px; }
.reply { display: flex; align-items: center; gap: 4px; color: #b5bac1; font-size: 13px; margin-left: -4px;
         position: relative; white-space: nowrap; }
.reply::before { content: ""; position: absolute; left: -38px; top: 9px; width: 30px; height: 10px;
                 border-left: 2px solid #4e5058; border-top: 2px solid #4e5058; border-top-left-radius: 6px; }
.reply img { width: 16px; height: 16px; border-radius: 50%; }
.reply .rname { color: #f2f3f5; font-weight: 600; opacity: .85; }
.reply .rtext { display: inline-block; overflow: hidden; text-overflow: ellipsis; max-width: 540px;
                vertical-align: bottom; }
.reply.gone { font-style: italic; color: #949ba4; }
.media img.pic { display: block; max-width: 420px; max-height: 340px; border-radius: 8px; margin-top: 4px; }
.file { display: inline-flex; gap: 10px; align-items: center; background: #2b2d31; border: 1px solid #1e1f22;
        border-radius: 8px; padding: 10px 14px; margin-top: 4px; max-width: 420px; }
.file .fname { color: #00a8fc; }
.file .fsize { color: #949ba4; font-size: 12px; }
.embed { background: #2b2d31; border-left: 4px solid #1e1f22; border-radius: 4px; padding: 8px 16px 12px 12px;
         margin-top: 4px; max-width: 432px; }
.embed .provider, .embed .eauthor { color: #b5bac1; font-size: 12px; }
.embed .etitle { color: #00a8fc; font-weight: 600; margin-top: 4px; }
.embed .edesc { font-size: 14px; margin-top: 4px; }
.embed .field { margin-top: 6px; font-size: 14px; }
.embed .field b { display: block; color: #f2f3f5; }
.embed img { max-width: 400px; max-height: 300px; border-radius: 4px; margin-top: 8px; display: block; }
.sticker { width: 160px; height: 160px; margin-top: 4px; display: block; object-fit: contain; }
.stickername { color: #949ba4; font-style: italic; }
.reactions { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
.reactions span { background: #2b2d31; border: 1px solid #3f4147; border-radius: 8px; padding: 1px 7px;
                  font-size: 14px; color: #b5bac1; }
.reactions img { width: 16px; height: 16px; vertical-align: -3px; }
.system { padding: 6px 48px 6px 72px; color: #949ba4; font-size: 14px; break-inside: avoid; position: relative; }
.system::before { content: "→"; position: absolute; left: 34px; color: #23a55a; }
.system.call::before { content: "📞"; left: 30px; }
.end { margin: 28px 16px 0 16px; text-align: center; color: #6d6f78; font-size: 12px; }
"""


def _size(n):
    return f"{n / 1024 / 1024:.1f} MB" if n >= 1024 * 1024 else f"{max(1, round(n / 1024))} KB"


def _day_label(day):
    return day.strftime("%B %-d, %Y") if os.name != "nt" else day.strftime("%B %#d, %Y")


def _time_label(when):
    return when.strftime("%-I:%M %p") if os.name != "nt" else when.strftime("%#I:%M %p")


def build_html(rows, title, subtitle, her_id, avatar="", images=True, names=None):
    """One discord-looking page for the whole chat. Messages from the same person close together are grouped
    under one name, like discord does, with a separator for each new day."""
    esc = html.escape
    names = {**(names or {}), **{r.author_id: r.name for r in rows}}
    out = [
        "<!doctype html><html><head><meta charset='utf-8'><title>",
        esc(title),
        "</title><style>",
        CSS,
        "</style></head><body><div class='head'>",
        f"<img src='{esc(avatar)}'>" if avatar and images else "",
        f"<div><h1>{esc(title)}</h1><div class='sub'>{esc(subtitle)}</div></div></div>",
    ]
    prev = None
    for r in rows:
        if prev is None or r.when.date() != prev.when.date():
            out.append(f"<div class='day'><span>{esc(_day_label(r.when))}</span></div>")
            prev = None
        if r.system:
            klass = "system call" if "call" in r.system.lower() else "system"
            out.append(
                f"<div class='{klass}'><b>{esc(r.name)}</b> {esc(r.system)} "
                f"<span class='time'>{esc(_time_label(r.when))}</span></div>"
            )
            prev = None
            continue
        first = prev is None or prev.author_id != r.author_id or r.reply is not None or r.when - prev.when > GROUP_GAP
        klass = "msg first" + (" replying" if r.reply else "") if first else "msg"
        parts = [f"<div class='{klass}'>"]
        if first:
            if r.reply:
                rname, ravatar, rtext = r.reply
                if rname is None:
                    parts.append(f"<div class='reply gone'>{esc(rtext)}</div>")
                else:
                    pic = f"<img src='{esc(ravatar)}'>" if images and ravatar else ""
                    parts.append(
                        f"<div class='reply'>{pic}<span class='rname'>@{esc(rname)}</span>"
                        f"<span class='rtext'>{markdown(rtext, names, images)[0]}</span></div>"
                    )
            if images:
                parts.append(f"<img class='avatar' src='{esc(r.avatar)}'>")
            her = " her" if r.author_id == her_id else ""
            parts.append(
                f"<div class='header'><span class='name{her}'>{esc(r.name)}</span>"
                f"<span class='time'>{esc(r.when.strftime('%d/%m/%Y'))} {esc(_time_label(r.when))}"
                f"</span></div>"
            )
        if r.text:
            body, jumbo = markdown(r.text, names, images)
            edited = "<span class='edited'>(edited)</span>" if r.edited else ""
            parts.append(f"<div class='text{' jumbo' if jumbo else ''}'>{body}{edited}</div>")
        if r.attachments:
            parts.append("<div class='media'>")
            for a in r.attachments:
                if a["kind"] == "image" and images:
                    parts.append(f"<img class='pic' src='{esc(a['url'])}' alt='{esc(a['name'])}'>")
                else:
                    icon = "🖼️" if a["kind"] == "image" else "🎞️" if a["kind"] == "video" else "📄"
                    parts.append(
                        f"<div class='file'>{icon}<div><div class='fname'>{esc(a['name'])}</div>"
                        f"<div class='fsize'>{esc(_size(a['size'] or 0))}</div></div></div>"
                    )
            parts.append("</div>")
        for e in r.embeds:
            parts.append(_embed_html(e, images))
        for s in r.stickers:
            if s["url"] and images:
                parts.append(f"<img class='sticker' src='{esc(s['url'])}' alt='{esc(s['name'])}'>")
            else:
                parts.append(f"<div class='stickername'>[sticker: {esc(s['name'])}]</div>")
        if r.reactions:
            pills = []
            for x in r.reactions:
                face = f"<img src='{esc(x['url'])}'>" if x["url"] and images else esc(x["emoji"] or "?")
                pills.append(f"<span>{face} {int(x['count'])}</span>")
            parts.append(f"<div class='reactions'>{''.join(pills)}</div>")
        parts.append("</div>")
        out.append("".join(parts))
        prev = r
    out.append(f"<div class='end'>end of the conversation · {len(rows)} messages</div></body></html>")
    return "".join(out)


def _embed_html(e, images):
    esc = html.escape
    if e["type"] in ("image", "gifv") and images and (e["thumbnail"] or e["image"] or e["url"]):
        return f"<div class='media'><img class='pic' src='{esc(e['thumbnail'] or e['image'] or e['url'])}'></div>"
    if not (e["title"] or e["description"] or e["provider"] or e["author"] or e["fields"]):
        return ""
    style = f" style='border-left-color:{esc(e['color'])}'" if e["color"] else ""
    bits = [f"<div class='embed'{style}>"]
    if e["provider"]:
        bits.append(f"<div class='provider'>{esc(e['provider'])}</div>")
    if e["author"]:
        bits.append(f"<div class='eauthor'>{esc(e['author'])}</div>")
    if e["title"]:
        bits.append(f"<div class='etitle'>{esc(e['title'])}</div>")
    if e["description"]:
        bits.append(f"<div class='edesc'>{markdown(e['description'][:600], {}, images)[0]}</div>")
    for name, value in e["fields"][:10]:
        bits.append(f"<div class='field'><b>{esc(name)}</b>{markdown(value[:300], {}, images)[0]}</div>")
    if images and (e["image"] or e["thumbnail"]):
        bits.append(f"<img src='{esc(e['image'] or e['thumbnail'])}'>")
    bits.append("</div>")
    return "".join(bits)


async def render_pdf(browser, page_html, workdir):
    """Prints the page with a headless chrome or edge. Returns the pdf path, or raises RuntimeError."""
    workdir = Path(workdir)
    page = workdir / "chat.html"
    pdf = workdir / "chat.pdf"
    page.write_text(page_html, encoding="utf-8")
    code, _ = await _run_browser(
        browser, workdir, "--no-pdf-header-footer", f"--print-to-pdf={pdf}", page.resolve().as_uri()
    )
    if not pdf.exists() or pdf.stat().st_size == 0:
        raise RuntimeError(f"the browser didn't make a pdf (exit code {code})")
    return pdf


async def _run_browser(browser, workdir, *args, capture=False):
    """Runs a headless chrome or edge. Returns its exit code and, with capture, what it printed."""
    proc = await asyncio.create_subprocess_exec(
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--disable-extensions",
        "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=30000",
        f"--user-data-dir={Path(workdir) / 'profile'}",
        *args,
        stdout=asyncio.subprocess.PIPE if capture else asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), RENDER_TIMEOUT)
    except TimeoutError:
        proc.kill()
        raise RuntimeError("the browser took too long to print it") from None
    return proc.returncode, (out or b"").decode("utf-8", "replace")


async def render_png(browser, page_html, workdir):
    """The page as one long png. It's measured first, then shot in slices and stitched together, since one huge
    screenshot isn't something a browser can be trusted with. The measuring script is ours: messages are escaped."""
    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError("png export needs pillow (pip install pillow)") from None
    workdir = Path(workdir)
    page = workdir / "chat.html"
    size = f"--window-size={PNG_WIDTH},{PNG_MEASURE_HEIGHT}"
    page.write_text(page_html.replace("</head>", f"{MEASURE}</head>", 1), encoding="utf-8")
    _, dom = await _run_browser(
        browser, workdir, size, "--hide-scrollbars", "--dump-dom", page.resolve().as_uri(), capture=True
    )
    found = re.search(r'data-height="(\d+)"', dom)
    if not found:
        raise RuntimeError("the browser couldn't measure the page")
    height = int(found.group(1))
    if height > PNG_MAX_HEIGHT:
        raise TooTall(f"that chat is too long for one image ({height} px tall), use --pdf instead")
    slices = []
    for top in range(0, height, PNG_SLICE):
        tall = min(PNG_SLICE, height - top)
        shot = workdir / f"slice-{top}.png"
        moved = f"<style>html {{ overflow: hidden; }} body {{ margin-top: -{top}px; }}</style></head>"
        page.write_text(page_html.replace("</head>", moved, 1), encoding="utf-8")
        await _run_browser(
            browser,
            workdir,
            f"--window-size={PNG_WIDTH},{max(tall, PNG_MEASURE_HEIGHT)}",
            "--hide-scrollbars",
            f"--screenshot={shot}",
            page.resolve().as_uri(),
        )
        if not shot.exists():
            raise RuntimeError("the browser didn't make a screenshot")
        slices.append((shot, top, tall))
    out = workdir / "chat.png"

    def stitch():
        whole = Image.new("RGB", (PNG_WIDTH, height), BACKGROUND)
        for shot, top, tall in slices:
            with Image.open(shot) as part:
                whole.paste(part.convert("RGB").crop((0, 0, PNG_WIDTH, tall)), (0, top))
        whole.save(out, compress_level=9)

    await asyncio.to_thread(stitch)
    return out


async def make(app, channel, workdir, browser, kind="pdf"):
    """The whole dm as a pdf or one long png. Returns (file, messages, with_pictures). If it's too big to upload even
    without pictures, with_pictures is None."""
    messages = [m async for m in channel.history(limit=None, oldest_first=True)]
    if not messages:
        raise RuntimeError("there's nothing in that dm")
    now = app.clock.now()
    rows = rows_from(messages, now.tzinfo)
    names = {u.id: _name(u) for m in messages for u in getattr(m, "mentions", None) or []}
    title, avatar, _ = describe(channel, app.user)
    subtitle = (
        f"{len(rows)} messages · {rows[0].when:%d %b %Y} to {rows[-1].when:%d %b %Y} · printed {now:%d %b %Y %H:%M}"
    )
    limit = NITRO_UPLOAD if app.cfg.nitro is True else FREE_UPLOAD
    render = render_png if kind == "png" else render_pdf
    out, too_tall = None, None
    for pictures in (True, False):
        page = build_html(rows, title, subtitle, app.user.id, avatar, images=pictures, names=names)
        try:
            out = await render(browser, page, workdir)
        except TooTall as e:
            out, too_tall = None, e
            continue
        if out.stat().st_size <= limit:
            return out, len(rows), pictures
        log.info("the printout is %s with pictures=%s, over the upload limit", _size(out.stat().st_size), pictures)
    if out is None:
        raise too_tall
    return out, len(rows), None


def describe(channel, me):
    """The printout's title and the picture at the top."""
    if isinstance(channel, discord.DMChannel) or getattr(channel, "recipient", None) is not None:
        other = channel.recipient
        return f"{_name(me)} & {_name(other)}", _avatar(other), getattr(other, "name", "")
    name = getattr(channel, "name", None) or ", ".join(_name(u) for u in getattr(channel, "recipients", []))
    return name or "group dm", "", name or "group"
