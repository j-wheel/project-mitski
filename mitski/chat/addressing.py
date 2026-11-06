import random
import re
import time
from dataclasses import dataclass

import discord

from mitski.brain.answers import keywords
from mitski.chat.messages import clean, short_name
from mitski.chat.patterns import JUST_HI, LOW_EFFORT, NEVER
from mitski.chat.state import Engagement
from mitski.core.component import Component

QUESTIONY = re.compile(
    r"\?|\b(?:what|whats|who|whos|when|where|why|how|which|do u|do you|can u|can you|would u|"
    r"would you|are u|are you|did u|did you|have u|have you|wanna|tell me)\b",
    re.I,
)
GREETING_TO = re.compile(
    r"^\W*(?:gm|gn|gmorning|good\s*(?:morning|night|evening|afternoon)|morning|mornin|night|nini|hi+|hey+|hello+|yo+|"
    r"sup|wsg|wassup|ty|thanks|thank\s*you|thx|tysm|bye+|cya|ily|ilysm|hbd|happy\s+birthday|welcome(?:\s+back)?|wb|"
    r"congrats|grats|gg|rip|love\s+(?:you|u)|miss\s+(?:you|u)|sorry|ok(?:ay)?|lol|lmao|omg|nah|yes|no)[\s,!.~:]+@?([\w.'-]{2,32})",
    re.I,
)
MAX_PIECES = 8
LEAD_IN = re.compile(r"\b(?:hey+|hi+|yo+|ok|okay|omg|bro|girl|lol|lmao|ugh|wait|and|but|so|oi|bruh|wtf|damn)\b")
TRAILING = re.compile(r"\b(?:lol|lmao|lmfao|haha\w*|hehe\w*|xd|fr|ngl|tbh|pls|plz|ok|okay|rn|bro|frfr|istg)\b")
ABOUT_HER = re.compile(
    r"^\W*(?:is|was|isn'?t|wasn'?t|has|had|does|did|doesn'?t|didn'?t|'s|s|will|would|can|could|should|might|and|or|"
    r"said|says|thinks?|seems?|got|gets|always|never|just|really|literally)\b",
    re.I,
)
GROUP_WORDS = set(
    [
        "everyone",
        "everybody",
        "all",
        "yall",
        "y'all",
        "yal",
        "chat",
        "guys",
        "gang",
        "peeps",
        "people",
        "ppl",
        "frens",
        "friends",
        "besties",
        "gamers",
        "fam",
        "folks",
        "lads",
        "girls",
        "boys",
        "bros",
        "homies",
        "team",
        "server",
        "squad",
    ]
)


@dataclass(frozen=True)
class Thing:
    text: str
    msg: object


def same_topic(a, b):
    words_a, words_b = keywords(a), keywords(b)
    return bool(words_a and words_b) and len(words_a & words_b) / min(len(words_a), len(words_b)) >= 0.5


def needs_own_answer(text):
    """A question or request, not a remark, a reaction or an emoji."""
    text = clean(text)
    if not re.search(r"[A-Za-z0-9]", text) or LOW_EFFORT.match(text) or JUST_HI.match(text):
        return False
    return bool(QUESTIONY.search(text))


def split_questions(text):
    pieces = [p.strip() for p in re.split(r"(?<=\?)\s+|\n+", text) if p.strip()]
    asks = [p for p in pieces if "?" in p and len(p.split()) >= 2]
    separate = []
    for ask in asks:
        if not any(same_topic(ask, other) for other in separate):
            separate.append(ask)
    return pieces if len(separate) >= 2 else [text]


class Addressing(Component):
    def __init__(self, app):
        super().__init__(app)
        self.triggers = [str(n).lower() for n in self.cfg.NAME_TRIGGERS or []]
        self.name_pattern = (
            re.compile(r"\b(" + "|".join(map(re.escape, self.triggers)) + r")\b", re.I) if self.triggers else None
        )

    def engage(self, channel_id, user_id, refill=False):
        key = (channel_id, user_id)
        boost = 2 if self.app.owner.is_owner(user_id) else 1
        e = self.state.engaged.get(key) or Engagement(NEVER)
        e.until = time.monotonic() + self.cfg.ENGAGE_SEC * boost
        if refill:
            e.budget = self.cfg.FOLLOWUP_BUDGET * boost
        self.state.engaged[key] = e

    def is_engaged(self, channel_id, user_id):
        e = self.state.engaged.get((channel_id, user_id))
        return e is not None and e.live()

    def talks_to_her(self, msg):
        if self.me in msg.mentions:
            return True
        ref = msg.reference.resolved if msg.reference else None
        if isinstance(ref, discord.Message) and ref.author.id == self.me.id:
            return True
        return bool(self.name_pattern and self.name_pattern.search(msg.content))

    def called_her(self, msg):
        if self.me not in msg.mentions:
            return False
        ref = msg.reference.resolved if msg.reference else None
        replying_to_her = getattr(getattr(ref, "author", None), "id", None) == self.me.id
        return not replying_to_her or f"<@{self.me.id}>" in msg.content or f"<@!{self.me.id}>" in msg.content

    def burst_of(self, target, msgs, window=150):
        out = [target]
        for m in reversed([m for m in msgs if m.id < target.id]):
            if m.author.id == self.me.id:
                to = self.state.addressed.get(m.id, "?")
                ref = m.reference.resolved if m.reference else None
                if to == target.author.id or (
                    to == "?" and isinstance(ref, discord.Message) and ref.author.id == target.author.id
                ):
                    break
                continue
            if m.author.id != target.author.id:
                continue
            if (out[0].created_at - m.created_at).total_seconds() > window or len(out) >= 5:
                break
            if m.guild is not None and self.for_someone_else(m) and not self.talks_to_her(m):
                continue
            out.insert(0, m)
        return out

    def burst_text(self, burst):
        return " / ".join(t for t in (self.messages.text(m) for m in burst) if t)

    def anchor_of(self, burst):
        def score(m):
            text = clean(m.content)
            s = (2 if self.talks_to_her(m) else 0) + (2 if QUESTIONY.search(text) else 0) + (1 if len(text) > 15 else 0)
            if LOW_EFFORT.match(text) or JUST_HI.match(text):
                s -= 1
            return s, m.id

        return max(burst, key=score)

    def pieces_of(self, burst):
        return [Thing(piece, m) for m in burst for piece in split_questions(self.messages.text(m))][:MAX_PIECES]

    def separate_things(self, pieces, thought):
        """The separate questions in what someone sent, each needing its own answer. Remarks, reactions and emojis
        never count: a person answers questions one by one, but reacts to a few remarks in a row as one thing."""
        if len(pieces) < 2:
            return list(pieces)
        if thought.topics:
            picked = self._distinct(pieces[i - 1] for i in thought.topics if 1 <= i <= len(pieces))
            if len(picked) >= 2:
                return picked
        return self._distinct(pieces) or pieces[-1:]

    @staticmethod
    def _distinct(pieces):
        out = []
        for piece in pieces:
            if needs_own_answer(piece.text) and not any(same_topic(piece.text, other.text) for other in out):
                out.append(piece)
        return out

    def juggling(self, channel_id, user_id, window=150):
        now = time.monotonic()
        busy = {u for (c, u) in self.state.waiting if c == channel_id}
        busy |= {
            u
            for (c, u), e in self.state.engaged.items()
            if c == channel_id and e.live(now) and now - self.state.last_msg_time.get((c, u), NEVER) < window
        }
        return busy - {user_id, self.me.id}

    def her_names(self):
        names = {short_name(self.me).lower(), self.me.name.lower()} | set(self.triggers)
        names |= {str(d.get("calls_her", {}).get("v", "")).lower() for d in self.memory.people.values()}
        return {n for n in names if n}

    def person_names(self, guild):
        names = set(self.state.known_names[guild.id]) | self.memory.all_names() if guild else self.memory.all_names()
        if guild is not None:
            for m in getattr(guild, "members", [])[:5000]:
                names |= {short_name(m).lower(), m.name.lower()}
        names |= {n.split()[0] for n in list(names) if " " in n}
        return {n for n in names if len(n) >= 3} - self.her_names()

    def addressee_hint(self, msg):
        if self.me in msg.mentions:
            return "her"
        if any(u.id != self.me.id for u in msg.mentions):
            return "other"
        text = clean(self.messages.with_mentions(msg)).lower()
        hers, people = self.her_names(), self.person_names(getattr(msg, "guild", None))
        m = GREETING_TO.match(text)
        if m:
            word = m.group(1).lower().strip(".'-")
            if word in hers:
                return "her"
            if word in GROUP_WORDS:
                return "all"
            if word in people:
                return "other"
        last = re.search(r"[,\s]@?([\w.'-]{3,32})\W*$", text)
        if last and last.group(1).lower() in people and len(text.split()) <= 12:
            return "other"
        return None

    def chimes_in(self, msg):
        if self.app.sleep.state_of(msg.channel):
            return False
        if msg.id not in self.state.chime_rolls:
            chance = (
                max(self.cfg.CHIME_IN_CHANCE, 0.6) if self.app.owner.is_owner(msg.author) else self.cfg.CHIME_IN_CHANCE
            )
            chance *= self.app.feelings.chime_factor(msg.author)
            self.state.chime_rolls[msg.id] = random.random() < chance
        return self.state.chime_rolls[msg.id]

    def aimed_at_her(self, msg, hers=()):
        """Strictly: was this said TO her? Not near her, not about her to someone else, not to anyone else at all.
        Used for anything that changes how she feels about someone, where a wrong guess would be unfair."""
        if isinstance(msg.channel, discord.DMChannel):
            return True
        replied_to = getattr(getattr(msg.reference.resolved if msg.reference else None, "author", None), "id", None)
        if self.target_of(msg) is not None or self.for_someone_else(msg):
            return False
        if self.me in msg.mentions or replied_to == self.me.id:
            return True
        return self.named_directly(msg.content) or self.answers_her(msg, hers)

    def named_directly(self, text):
        """Her name used to talk to her ("mitski ur annoying", "hey mitski", "ur so cute mitski"), not to talk
        about her ("mitski is annoying", "i think mitski is cute"). Only her real names, not pet names."""
        lowered = clean(text or "").lower()
        names = {short_name(self.me).lower(), self.me.name.lower(), *self.triggers} - {""}
        for name in names:
            for m in re.finditer(r"(?<!\w)" + re.escape(name) + r"(?!\w)", lowered):
                before, after = lowered[: m.start()], lowered[m.end() :]
                if not re.search(r"[a-z0-9]", TRAILING.sub("", after)):
                    return True
                if not re.search(r"[a-z0-9]", LEAD_IN.sub("", before)) and not ABOUT_HER.match(after):
                    return True
        return False

    def answers_her(self, msg, hers=()):
        """Their message comes straight after something she said to them, with nobody else talking in between."""
        events = dict(self.state.chan_log.get(msg.channel.id, ()))
        last = self.app.sender.last_sent.get(msg.channel.id)
        for mid in [m.id for m in hers] + ([last] if last else []):
            events.setdefault(mid, self.me.id)
        for mid in sorted((m for m in events if m < msg.id), reverse=True):
            uid = events[mid]
            if uid == msg.author.id:
                continue
            return uid == self.me.id and self.state.addressed.get(mid) == msg.author.id
        return False

    def target_of(self, msg):
        """The other person a message is aimed at (a reply to them or a ping), or None."""
        author = getattr(msg.reference.resolved if msg.reference else None, "author", None)
        if author is not None and author.id not in (self.me.id, msg.author.id):
            return author
        return next((u for u in msg.mentions if u.id not in (self.me.id, msg.author.id)), None)

    def is_follow_up(self, msg):
        key = (msg.channel.id, msg.author.id)
        e = self.state.engaged.get(key)
        if e is None or not e.live() or e.budget <= 0:
            return False
        if self.for_someone_else(msg) and not self.chimes_in(msg):
            return False
        e.budget -= 1
        return True

    def for_someone_else(self, msg):
        ref = msg.reference.resolved if msg.reference else None
        if isinstance(ref, discord.Message) and ref.author.id not in (self.me.id, msg.author.id):
            return True
        if any(u.id not in (self.me.id, msg.author.id) for u in msg.mentions):
            return True
        if self.addressee_hint(msg) == "other":
            return True
        text = msg.content.lower()
        words = set(re.findall(r"[\w.']+", text))
        names = (
            set(self.state.known_names[msg.guild.id])
            | {str(d.get("name", "")).lower() for d in self.memory.people.values()}
            | self.memory.all_names()
        )
        names -= {(self.memory.call_name(msg.author) or "").lower()}
        names -= {short_name(msg.author).lower(), msg.author.name.lower(), short_name(self.me).lower(), ""}
        names -= set(self.triggers)
        for n in names:
            if len(n) >= 3 and (n in words or (" " in n and re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", text))):
                return True
        return False

    def chatting_with(self, guild_id, uid):
        return any(
            k[1] == uid
            and self.is_engaged(*k)
            and getattr(getattr(self.app.get_channel(k[0]), "guild", None), "id", None) == guild_id
            for k in list(self.state.engaged)
        )
