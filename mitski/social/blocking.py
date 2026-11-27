import asyncio
import random
import re

import discord

from mitski.core import logs
from mitski.core.component import Component
from mitski.core.text import cut
from mitski.core.texts import wording

log = logs.get("blocking")

SAYS_BLOCK = re.compile(
    r"\b(?:i'?m|im|i am|i'?ll|ill|i will|ima|imma|gonna|going to|about to|finna|time to)\s+"
    r"(?:just\s+|literally\s+|actually\s+|so\s+|fr\s+|now\s+)?block(?:ing)?\s+(?:u|you|ya|ur\s+\w+|this\s+\w+)\b|"
    r"\b(?:ur|you'?re|youre|u\s*r)\s+(?:so\s+|now\s+|officially\s+)?blocked\b|^\W*blocked\b|"
    r"\bblock(?:ing|ed)\s+(?:u|you)\s+(?:now|rn|bye)\b",
    re.I,
)
NOT_REALLY = re.compile(
    r"\b(?:if|unless|would|wouldn'?t|almost|jk|joking|kidding|not|never|don'?t make me|before i)\b|/j\b", re.I
)
DELAY = (2, 6)
NOTE = wording("persona.blocking")


def means_block(lines):
    return any(SAYS_BLOCK.search(line) and not NOT_REALLY.search(line) for line in lines)


class Blocking(Component):
    def __init__(self, app):
        super().__init__(app)
        self.blocked = set()

    @property
    def on(self):
        return bool(self.cfg.BLOCKING)

    def note(self):
        return NOTE if self.on else ""

    def sync(self):
        for r in list(getattr(self.app.client, "relationships", None) or []):
            self.relationship(r)

    def relationship(self, relationship):
        user = getattr(relationship, "user", None)
        if user is None:
            return
        if relationship.type is discord.RelationshipType.blocked:
            if user.id not in self.blocked:
                self.blocked.add(user.id)
                self.cfg.ignored.add(user.id)
                self.state.forget_user(user.id)
                log.info("%s is blocked, so she ignores them", user)
        elif user.id in self.blocked:
            self._let_back(user.id)

    def unblocked(self, relationship):
        user = getattr(relationship, "user", None)
        if user is not None and user.id in self.blocked:
            self._let_back(user.id)

    def _let_back(self, uid):
        self.blocked.discard(uid)
        if uid not in self.cfg.saved_list("IGNORE_USERS"):
            self.cfg.ignored.discard(uid)
        log.info("%s isn't blocked anymore", uid)

    def said(self, lines, user):
        if not self.on or user is None or not means_block(lines):
            return
        if self.app.owner.is_owner(user) or (self.me and user.id == self.me.id) or user.id in self.blocked:
            return
        self.app.tasks.spawn(self.block(user, cut(" | ".join(lines), 120)), name=f"block-{user.id}")

    async def block(self, user, why="", delay=True):
        if self.app.owner.is_owner(user):
            return "she can't block the account that runs her commands"
        if delay:
            await asyncio.sleep(random.uniform(*DELAY))
        target = self.app.client.get_user(user.id) or user
        try:
            await target.block()
        except (discord.HTTPException, AttributeError) as e:
            log.warning("couldn't block %s: %s", user, e)
            return f"couldn't block {user}: {e}"
        self.blocked.add(user.id)
        self.cfg.ignored.add(user.id)
        self.state.forget_user(user.id)
        log.info("blocked %s (%s)", user, why or "asked to")
        await self.app.relay.post(f"**blocked** {user} `{user.id}`" + (f"\n> {why}" if why else ""))
        return f"blocked {user} `{user.id}`"

    async def unblock(self, uid):
        user = self.app.client.get_user(uid)
        if user is None:
            try:
                user = await self.app.client.fetch_user(uid)
            except discord.HTTPException as e:
                return f"couldn't find `{uid}`: {e}"
        try:
            await user.unblock()
        except discord.HTTPException as e:
            return f"couldn't unblock {user}: {e}"
        self._let_back(uid)
        return f"unblocked {user} `{uid}`"
