import time

from mitski.core import logs
from mitski.core.collections import BoundedDict
from mitski.core.component import Component
from mitski.core.text import cut
from mitski.core.texts import say, wording

log = logs.get("reacted")

RECENT_MIN = 20
IN_NOTE = 4
LAUGH = {"😂", "🤣", "😭", "💀", "😹", "☠️", "😆", "😅"}
LOVE = {"❤️", "❤", "🥰", "😍", "💕", "💖", "💗", "💞", "💓", "🫶", "😘", "🤍", "🩷", "💜", "💙", "🖤", "♥️"}
NICE = {"👍", "🔥", "💯", "👏", "🙌", "✨", "⭐", "🌟", "🎉", "🥹", "😊", "🫡", "✅", "👑"}
MEAN = {"🤡", "👎", "🙄", "🤓", "💩", "🖕", "😒", "🥱", "🤢", "🤮", "😐", "🗑️"}
MOOD = (
    (LAUGH, "amused", 0.08, wording("chat.reaction_laughed")),
    (LOVE, "happy", 0.06, wording("chat.reaction_hearted")),
    (NICE, "happy", 0.04, wording("chat.reaction_liked")),
    (MEAN, "irritated", 0.06, wording("chat.reaction_clown")),
)


def emoji_text(emoji):
    if getattr(emoji, "is_custom_emoji", lambda: False)():
        return f":{emoji.name}:"
    return str(getattr(emoji, "name", None) or emoji)


class ReactionsSeen(Component):
    def __init__(self, app):
        super().__init__(app)
        self.mine = BoundedDict(800)

    def sent(self, msg_id, channel_id, text):
        self.mine[msg_id] = {"channel": channel_id, "text": text, "t": time.time(), "by": {}}

    def added(self, payload):
        entry = self.mine.get(payload.message_id)
        if entry is None or (self.me and payload.user_id == self.me.id) or payload.user_id in self.cfg.ignored:
            return False
        emoji = emoji_text(payload.emoji)
        got = entry["by"].setdefault(payload.user_id, [])
        if emoji in got:
            return False
        got.append(emoji)
        entry["seen"] = time.time()
        who = self.app.get_user(payload.user_id)
        log.info("%s reacted %s to her %r", who or payload.user_id, emoji, cut(entry["text"], 60))
        for group, feeling, amount, why in MOOD:
            if emoji in group:
                self.app.feelings.feel(feeling, amount, why)
                break
        return True

    def removed(self, payload):
        entry = self.mine.get(payload.message_id)
        if entry is None:
            return
        got = entry["by"].get(payload.user_id, [])
        emoji = emoji_text(payload.emoji)
        if emoji in got:
            got.remove(emoji)
        if not got:
            entry["by"].pop(payload.user_id, None)

    def note(self, channel_id, now=None):
        now = now or time.time()
        bits = []
        for entry in sorted(self.mine.values(), key=lambda e: -e.get("seen", 0)):
            if entry["channel"] != channel_id or not entry["by"] or now - entry.get("seen", 0) > RECENT_MIN * 60:
                continue
            people = []
            for uid, emojis in entry["by"].items():
                user = self.app.get_user(uid)
                name = self.messages.call(user) if user is not None else "someone"
                people.append(f"{name} {' '.join(emojis)}")
            bits.append(say("chat.reaction_on", people=", ".join(people), message=cut(entry["text"], 80)))
            if len(bits) >= IN_NOTE:
                break
        if not bits:
            return ""
        return (wording("chat.reactions_lately") + " ") + "; ".join(bits) + wording("chat.reactions_end")
