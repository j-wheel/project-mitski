import discord

from mitski.chat.messages import short_name
from mitski.core import logs
from mitski.core.component import Component
from mitski.core.text import cut
from mitski.memory import activity

log = logs.get("presence")


ACTIVITY_TYPES = {
    "playing": discord.ActivityType.playing,
    "watching": discord.ActivityType.watching,
    "listening": discord.ActivityType.listening,
    "competing": discord.ActivityType.competing,
}
STATUS_TYPES = {
    "online": discord.Status.online,
    "idle": discord.Status.idle,
    "dnd": discord.Status.dnd,
    "invisible": discord.Status.invisible,
}


def is_spotify(a):
    return type(a).__name__ == "Spotify" and getattr(a, "title", None)


def game_name(a):
    t = getattr(a, "type", None)
    if t == discord.ActivityType.playing:
        return getattr(a, "name", None)
    if t == discord.ActivityType.streaming:
        game = getattr(a, "state", None) if hasattr(a, "state") else getattr(a, "game", None)
        return game or getattr(a, "details", None) or getattr(a, "name", None)
    return None


def describe_activity(a):
    t = getattr(a, "type", None)
    if is_spotify(a):
        return f'listening to "{a.title}" by {a.artist} on spotify'
    if t == discord.ActivityType.custom:
        text = (
            next((x for x in (getattr(a, "state", None), getattr(a, "name", None)) if x and x != "Custom Status"), "")
            or ""
        )
        return f'has their status set to "{cut(text.strip(), 80)}"' if text.strip() else None
    if t == discord.ActivityType.streaming:
        what = game_name(a)
        return f"streaming {what}" if what else "streaming"
    name = getattr(a, "name", None)
    verb = {
        discord.ActivityType.playing: "playing",
        discord.ActivityType.watching: "watching",
        discord.ActivityType.listening: "listening to",
        discord.ActivityType.competing: "competing in",
    }.get(t)
    if not (verb and name):
        return None
    bits = [b for b in (getattr(a, "details", None), getattr(a, "state", None)) if b]
    return f"{verb} {name}" + (f" ({cut(', '.join(bits), 80)})" if bits else "")


def doing_now(m):
    out = []
    for a in getattr(m, "activities", None) or ():
        t = getattr(a, "type", None)
        if is_spotify(a):
            artist = "; ".join(getattr(a, "artists", None) or []) or getattr(a, "artist", "")
            out.append(
                {
                    "kind": "music",
                    "title": getattr(a, "title", ""),
                    "artist": artist,
                    "track": getattr(a, "track_id", None),
                }
            )
        elif game_name(a):
            out.append({"kind": "game", "name": game_name(a)})
        elif t == discord.ActivityType.watching and getattr(a, "name", None):
            out.append({"kind": "watching", "name": a.name})
        elif t == discord.ActivityType.custom:
            text = next(
                (x for x in (getattr(a, "state", None), getattr(a, "name", None)) if x and x != "Custom Status"), ""
            )
            if text:
                out.append({"kind": "status", "text": text})
    return out


VERBS = {"playing": "playing", "watching": "watching", "listening": "listening to", "competing": "competing in"}


class Profiles(Component):
    def current_activity(self):
        status = self.app.owner.status
        if status is not None:
            return status.get("type") or "", status.get("text") or ""
        return str(self.cfg.ACTIVITY_TYPE or "").lower(), self.cfg.ACTIVITY_TEXT or ""

    async def apply(self):
        status = STATUS_TYPES.get(str(self.app.routine.status()).lower(), discord.Status.online)
        kind, text = self.current_activity()
        act = discord.Activity(type=ACTIVITY_TYPES[kind], name=text) if kind in ACTIVITY_TYPES and text else None
        await self.app.change_presence(status=status, activity=act)

    def own_status(self):
        kind, text = self.current_activity()
        verb = VERBS.get(kind)
        return f"Your discord status says you're {verb} {text}." if verb and text else ""

    def blurb(self, user, guild):
        if not self.cfg.PROFILES or user is None:
            return ""
        m = self.messages.member(user, guild)
        if m is None:
            return ""
        name = short_name(m)
        now = discord.utils.utcnow()
        bits = []
        acts = [d for d in (describe_activity(a) for a in (m.activities or ())) if d]
        if acts:
            bits.append(f"Right now {name} is " + ", and ".join(acts[:3]) + ".")
            known = (
                activity.right_now(self.memory.get(m.id), doing_now(m), self.app.tracker, m.id)
                if self.cfg.MEMORY
                else []
            )
            if known:
                bits.append("About that: " + "; ".join(known) + ".")
        if m.status not in (discord.Status.offline, discord.Status.invisible) and m.is_on_mobile():
            bits.append(f"{name} is on their phone.")
        if guild is not None and isinstance(m, discord.Member):
            roles = [r.name for r in reversed(m.roles) if not r.is_default() and not r.managed][:3]
            if roles:
                bits.append(f"Their roles here: {', '.join(roles)}.")
            if m.premium_since:
                bits.append(f"{name} boosts this server.")
            if m.joined_at and (now - m.joined_at).days < 7:
                bits.append(f"{name} only joined this server recently.")
        if (now - m.created_at).days < 30:
            bits.append(f"{name}'s discord account is brand new.")
        return " ".join(bits)

    def track(self, before, after):
        if not (self.cfg.PROFILES and self.cfg.PROFILE_TRACK and self.cfg.MEMORY):
            return
        if not isinstance(after, discord.Member):
            return
        if getattr(after, "bot", False):
            return
        d = self.memory.get(after.id)
        if not d:
            return
        for event in self.app.tracker.sync(d, after.id, doing_now(after)):
            log.info("%s: %s", short_name(after), event)
        self.memory.mark_dirty()
