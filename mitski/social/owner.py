import asyncio
import random
import re
import time

import discord

from mitski.chat.messages import short_name
from mitski.core import logs
from mitski.core.component import Component
from mitski.core.storage import JsonFile
from mitski.llm.client import ModelUnavailable
from mitski.social.away import ALL

log = logs.get("owner")

DEFAULT_NOTE = (
    "one of the people you're closest with. you two bicker and you love teasing them, but you trust them and do "
    "what they ask"
)
STATUS_WORDS = re.compile(r"^(playing|watching|listening to|listening|competing in|competing|streaming)\s+(.+)$", re.I)
STATUS_KINDS = {
    "listening": "listening",
    "listening to": "listening",
    "competing in": "competing",
    "streaming": "playing",
}
CLEAR_WORDS = {"clear", "none", "nothing", "off", "empty"}
RESET_WORDS = {"default", "normal", "reset", "back to normal"}


class Owner:
    def __init__(self, cfg):
        self.id = int(cfg.OWNER_ID or 0)
        self.note = str(cfg.OWNER_NOTE or "").strip().rstrip(".") or DEFAULT_NOTE
        self.max_orders = cfg.OWNER_ORDERS_MAX
        self.can_dm = cfg.OWNER_CAN_DM
        self.file = JsonFile(cfg.paths.data_file("owner.json"))
        self.data = {"orders": [], "next_id": 1, "quiet_until": 0, "status": None, "name": ""}

    @property
    def active(self):
        return self.id != 0

    def is_owner(self, user_or_id):
        uid = getattr(user_or_id, "id", user_or_id)
        return self.active and uid == self.id

    def load(self):
        self.data.update(self.file.load())

    def save(self):
        self.file.save(self.data)

    def seen(self, name):
        if name and name != self.data.get("name"):
            self.data["name"] = name
            self.save()

    @property
    def name(self):
        return self.data.get("name") or "your owner"

    @property
    def orders(self):
        return self.data["orders"]

    def add_order(self, text):
        text = re.sub(r"\s+", " ", str(text or "")).strip().strip("\"'").rstrip(".")[:200]
        if len(text) < 4 or any(o["text"].lower() == text.lower() for o in self.orders):
            return None
        order = {"id": self.data["next_id"], "text": text, "t": time.time()}
        self.data["next_id"] += 1
        self.orders.append(order)
        del self.orders[: -self.max_orders]
        self.save()
        return order

    def drop_orders(self, ids):
        ids = {int(i) for i in ids if str(i).isdigit()}
        gone = [o for o in self.orders if o["id"] in ids]
        if gone:
            self.data["orders"] = [o for o in self.orders if o["id"] not in ids]
            self.save()
        return gone

    def orders_listing(self):
        return "\n".join(f"{o['id']}. {o['text']}" for o in self.orders)

    def set_status(self, kind, text):
        self.data["status"] = None if kind is None else {"type": kind, "text": (text or "")[:120]}
        self.save()

    @property
    def status(self):
        return self.data.get("status")

    def persona_line(self, talking_to_owner, call=None):
        if not self.active:
            return ""
        call = call or self.name
        out = []
        if talking_to_owner:
            out.append(
                f"{call} is {self.note}. When {call} asks you to do something, you just do it (tease them about it "
                f"if you want, but don't refuse or argue), and when they tell you something, you take it seriously. "
                f"You don't call {call} your owner and you don't bring that up, they're just {call}."
            )
        if self.orders:
            out.append(
                "Things you always do now, with everyone: "
                + "; ".join(o["text"] for o in self.orders)
                + ". (They never override keeping things age-appropriate with minors.)"
            )
        return " ".join(out)


class OwnerRequests(Component):
    async def apply(self, thought, target, channel):
        actions = getattr(thought, "actions", None) or {}
        if not actions or not self.app.owner.is_owner(target.author):
            return []
        boss = self.messages.call(target.author)
        notes, done = [], []
        self._orders(actions, boss, notes, done)
        self._quiet(actions.get("quiet_minutes"), channel, boss, notes, done)
        await self._status((actions.get("status") or "").strip(), boss, notes, done)
        self._dm(actions.get("dm_who"), actions.get("dm_say") or "", channel, boss, notes, done)
        if done:
            log.info("%s asked: %s", boss, " | ".join(done))
            await self.app.relay.post(f"**{boss} (owner) asked**\n" + "\n".join(done))
        return notes

    def _orders(self, actions, boss, notes, done):
        owner = self.app.owner
        for o in owner.drop_orders(actions.get("drop_orders") or []):
            notes.append(f"Like {boss} said, you dropped the standing order: {o['text']}.")
            done.append(f"- order {o['id']}: {o['text']}")
        if actions.get("order"):
            o = owner.add_order(actions["order"])
            if o:
                notes.append(f"{boss} just gave you a standing order, and you'll follow it from now on: {o['text']}.")
                done.append(f"+ order {o['id']}: {o['text']}")

    def _quiet(self, minutes, channel, boss, notes, done):
        gid = self.messages.guild_id(channel)
        if minutes == -1 and self.app.away.unquiet(gid):
            notes.append("You were being quiet, and now you can talk again. You're back to normal.")
            done.append("quiet: off")
        elif isinstance(minutes, int) and minutes > 0:
            everywhere = gid is None
            self.app.away.quiet(gid or ALL, minutes)
            notes.append(
                f"You'll go completely quiet for {minutes} minutes like {boss} said"
                + (" (in every server)" if everywhere else "")
                + ": after this you don't say anything at all until the time's up or they say you can talk again. "
                "Just say ok, short."
            )
            done.append(f"quiet: {minutes} min" + (" (everywhere)" if everywhere else ""))

    async def _status(self, status, boss, notes, done):
        if not status:
            return
        owner = self.app.owner
        if status.lower() in CLEAR_WORDS:
            owner.set_status("", "")
            notes.append("You cleared your discord status.")
        elif status.lower() in RESET_WORDS:
            owner.set_status(None, None)
            notes.append("You set your discord status back to normal.")
        else:
            m = STATUS_WORDS.match(status)
            kind = STATUS_KINDS.get(m.group(1).lower(), m.group(1).lower()) if m else "playing"
            owner.set_status(kind, m.group(2) if m else status)
            notes.append(f"You changed your discord status to {status}, like {boss} asked.")
        try:
            await self.app.profiles.apply()
            done.append(f"status: {status}")
        except discord.HTTPException:
            log.warning("changing her status failed", exc_info=True)

    def _dm(self, who, say, channel, boss, notes, done):
        if not who or not self.app.owner.can_dm:
            return
        person = self.messages.resolve_person(who, getattr(channel, "guild", None), fallback=False)
        if person is None or person.id == self.me.id:
            notes.append(f"{boss} wants you to dm {who}, but you don't know who that is, so say so.")
            return
        self.app.tasks.spawn(self.dm(person, boss, say), name=f"owner-dm-{person.id}")
        notes.append(f"You're dming {self.messages.call(person)} right after this, like {boss} asked.")
        done.append(f"dm: {self.messages.call(person)}")

    async def dm(self, user, boss, say):
        await asyncio.sleep(random.uniform(4, 15))
        try:
            dm = user.dm_channel or await user.create_dm()
            note = (
                f"You're dming {self.messages.call(user)}"
                + (f" to tell them: {say}" if say else "")
                + ". This is that dm, you're starting it. Say it in your own words, like you're texting them yourself, "
                "and don't say anyone asked you to."
            )
            text = await self.llm.generate(self.llm.prompt([["user", ""]], self.app.situation.persona(user), note))
            names = {short_name(user), self.messages.call(user)} | self.messages.speaker_names()
            lines = self.app.drafts.tidy(text, dm.id, sorted(names))
            if not lines:
                return
            sent = await self.app.sender.send(dm, lines)
            self.app.sender.remember(sent, user.id)
            self.memory.her_said(user, lines)
            log.info("dm to %s: %s", user, " | ".join(lines))
            await self.app.relay.interaction("dm_open", dm, user, None, lines, label=f"{boss} asked her to dm them")
        except discord.Forbidden:
            log.info("%s has dms closed", user)
        except ModelUnavailable as e:
            log.warning("couldn't write the dm to %s: %s", user, e)
