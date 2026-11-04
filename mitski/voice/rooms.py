import re

GOOD_ROOM = re.compile(
    r"general|chill|lounge|hang|vc|voice|chat|talk|gaming|game|main|social|cozy|comfy|friends|squad|party|duo|trio",
    re.I,
)
BAD_ROOM = re.compile(
    r"afk|music|stage|private|priv|staff|mod|admin|locked|meeting|event|stream|radio|bot|24/7|study|focus|record|"
    r"interview|support|ticket|waiting|jail|timeout",
    re.I,
)


def word_in(name, text):
    return len(name) >= 3 and re.search(r"(?<!\w)" + re.escape(name.lower()) + r"(?!\w)", text) is not None


def joinable(channel):
    guild = channel.guild
    if channel == getattr(guild, "afk_channel", None) or getattr(guild, "me", None) is None:
        return False
    try:
        perms = channel.permissions_for(guild.me)
    except (AttributeError, TypeError):
        return False
    if not (perms.view_channel and perms.connect and perms.speak):
        return False
    limit = getattr(channel, "user_limit", 0) or 0
    return not limit or len(getattr(channel, "voice_states", {})) < limit or perms.move_members


def room_score(channel):
    limit = getattr(channel, "user_limit", 0) or 0
    return (
        2 * bool(GOOD_ROOM.search(channel.name))
        - 3 * bool(BAD_ROOM.search(channel.name))
        - 2 * (0 < limit <= 2)
        - 0.01 * getattr(channel, "position", 0)
    )


class RoomPicker:
    def __init__(self, people):
        self.people = people

    def pick(self, msg, me_id, empty_ok=False):
        guild = msg.guild
        text = (msg.content or "").lower()
        rooms = [c for c in guild.voice_channels if joinable(c)]
        for found in (
            self._mentioned(msg, rooms),
            self._named(rooms, text),
            self._where_mentioned(msg, rooms, me_id),
            self._where_named(guild, rooms, text),
            self._theirs(msg, rooms),
            self._busiest(rooms),
        ):
            if found is not None:
                return found
        if not empty_ok or not rooms:
            return None, ""
        best = max(rooms, key=room_score)
        return (best, "an empty vc") if room_score(best) > -2 else (None, "")

    @staticmethod
    def _mentioned(msg, rooms):
        for c in getattr(msg, "channel_mentions", None) or []:
            if c in rooms:
                return c, "the vc they named"
        return None

    @staticmethod
    def _named(rooms, text):
        named = [c for c in rooms if word_in(c.name, text)]
        return (max(named, key=lambda c: len(c.name)), "the vc they named") if named else None

    @staticmethod
    def _where_mentioned(msg, rooms, me_id):
        for u in getattr(msg, "mentions", None) or []:
            if u.id == me_id:
                continue
            member = msg.guild.get_member(u.id)
            channel = getattr(getattr(member, "voice", None), "channel", None)
            if channel is not None and channel in rooms:
                return channel, f"where {getattr(member, 'display_name', u.name)} is"
        return None

    def _where_named(self, guild, rooms, text):
        for c in rooms:
            for uid in self.people(c):
                member = guild.get_member(uid)
                names = {str(getattr(member, a, "") or "") for a in ("display_name", "name")}
                if any(word_in(n, text) for n in names):
                    return c, f"where {getattr(member, 'display_name', uid)} is"
        return None

    @staticmethod
    def _theirs(msg, rooms):
        channel = getattr(getattr(msg.author, "voice", None), "channel", None)
        return (channel, "their vc") if channel is not None and channel in rooms else None

    def _busiest(self, rooms):
        busy = [c for c in rooms if self.people(c)]
        return (max(busy, key=lambda c: len(self.people(c))), "the vc with the most people") if busy else None
