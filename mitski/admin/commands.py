import re
from dataclasses import dataclass
from datetime import datetime

import discord
import yaml

from mitski.admin.registry import help_text, parse
from mitski.config import ConfigError, prefix_problem
from mitski.core import logs
from mitski.core.component import Component
from mitski.reminders.timing import describe
from mitski.social.away import ALL

log = logs.get("commands")

CHUNK = 1900
HOURS = re.compile(r"(?<![\d.])(\d{1,2}(?:\.\d+)?)(?![\d.])")
SMALL_NUMBER = re.compile(r"(?<!\d)\d{1,6}(?!\d)")
CANCEL_WORDS = re.compile(r"\b(?:cancel|remove|delete|forget)\b")
MEMORY_COMMANDS = {"mem", "forget", "note", "set"}


@dataclass(frozen=True)
class LiveList:
    key: str
    added: str
    already: str
    removed: str
    missing: str


CHANNELS = LiveList("CHANNELS", "+ {}", "already in {}", "- {}", "{} wasn't in her channels")
IGNORED = LiveList(
    "IGNORE_USERS", "+ ignoring {}", "already ignoring {}", "- not ignoring {} anymore", "wasn't ignoring {}"
)
NO_SLEEP = LiveList(
    "SLEEP_EXCLUDE",
    "+ never sleeps in {}",
    "already never sleeps in {}",
    "- can sleep in {} again",
    "{} wasn't excluded",
)
NEEDS_IDS = {"addchannel", "delchannel", "ignoreuser", "unignoreuser", "sleepexclude", "sleepinclude", "sleep"}


def pieces(text, size=CHUNK):
    while len(text) > size:
        at = text.rfind("\n\n", 0, size)
        at = at if at > 0 else text.rfind("\n", 0, size)
        at = at if at > 0 else size
        yield text[:at]
        text = text[at:].lstrip("\n")
    if text:
        yield text


class AdminCommands(Component):
    def can_use(self, msg):
        where = self.cfg.COMMAND_CHANNEL
        return self.app.owner.is_owner(msg.author) and (not where or msg.channel.id == where)

    def guild_label(self, gid):
        g = self.messages.guild(gid)
        return f"{g.name} `{g.id}`" if g is not None else f"`{gid}` (she isn't in that server)"

    def channel_label(self, cid):
        ch = self.app.get_channel(cid)
        if ch is None:
            return f"`{cid}` (she can't see that channel)"
        where = getattr(getattr(ch, "guild", None), "name", None)
        return f"#{getattr(ch, 'name', cid)} `{cid}`" + (f" ({where})" if where else "")

    def user_label(self, uid):
        u = self.app.get_user(uid)
        return f"<@{uid}> `{uid}`" + (f" ({u.name})" if u is not None else "")

    def server_ids(self, ids):
        return list(dict.fromkeys(getattr(self.messages.guild(i), "id", i) for i in ids))

    def forget_user(self, uid):
        self.state.forget_user(uid)
        return self.memory.people.pop(str(uid), None) is not None

    async def dispatch(self, msg):
        call = parse(msg.content, self.cfg.COMMAND_PREFIX)
        if call is None:
            return False
        if self.can_use(msg):
            await self._run(call, msg.channel)
        return True

    async def _run(self, call, channel):
        if call.name in MEMORY_COMMANDS:
            await self.memory.command(channel, call.name, call.rest.split())
            return
        try:
            out = await getattr(self, f"_{call.name}")(call)
        except (OSError, ValueError, yaml.YAMLError, ConfigError) as e:
            out = [f"changed it for now, but couldn't save it to the config: {e}"]
            log.warning("saving %s failed", call.cmd, exc_info=True)
        if call.name in NEEDS_IDS and not call.ids:
            out.append(f"give me one or more ids, like `{call.cmd} 123456789012345678`")
        elif call.name in NEEDS_IDS:
            log.info("%s %s", call.cmd, " ".join(map(str, call.ids)))
        await self.reply(channel, "\n".join(out))

    async def reply(self, channel, text):
        for piece in pieces(text):
            sent = await channel.send(piece, allowed_mentions=discord.AllowedMentions.none())
            self.state.command_replies.add(sent.id)

    def _add(self, spec, live, ids, label, refuse=None, after=None):
        saved, out = self.cfg.saved_list(spec.key), []
        for i in ids:
            problem = refuse(i) if refuse else None
            if problem:
                out.append(problem)
            elif i in live and i in saved:
                out.append(spec.already.format(label(i)))
            else:
                if i not in saved:
                    saved.append(i)
                live.add(i)
                out.append(spec.added.format(label(i)) + ((after(i) if after else "") or ""))
        if ids:
            self.cfg.save_list(spec.key, saved)
        return out

    def _remove(self, spec, live, ids, label, after=None):
        saved, out = self.cfg.saved_list(spec.key), []
        for i in ids:
            if i not in live and i not in saved:
                out.append(spec.missing.format(label(i)))
                continue
            live.discard(i)
            saved = [s for s in saved if s != i]
            if after:
                after(i)
            out.append(spec.removed.format(label(i)))
        if ids:
            self.cfg.save_list(spec.key, saved)
        return out

    def _not_a_chat_channel(self, cid):
        return f"`{cid}` is the log channel, she doesn't chat there" if cid == self.cfg.LOG_CHANNEL else None

    def _cant_ignore(self, uid):
        if self.me and uid == self.me.id:
            return "that's her own id, she has to see her own messages"
        if self.app.owner.is_owner(uid):
            return "that's her owner, she can't ignore them"
        return None

    def _forget_on_ignore(self, uid):
        return " (and forgot what she knew about them)" if self.forget_user(uid) else ""

    def _wake_up(self, gid):
        self.app.away.wake(gid)
        return ""

    async def _addchannel(self, call):
        return self._add(CHANNELS, self.cfg.channels, call.ids, self.channel_label, refuse=self._not_a_chat_channel)

    async def _delchannel(self, call):
        return self._remove(CHANNELS, self.cfg.channels, call.ids, self.channel_label, after=self.state.forget_channel)

    async def _ignoreuser(self, call):
        return self._add(
            IGNORED, self.cfg.ignored, call.ids, self.user_label, refuse=self._cant_ignore, after=self._forget_on_ignore
        )

    async def _unignoreuser(self, call):
        return self._remove(IGNORED, self.cfg.ignored, call.ids, self.user_label)

    async def _sleepexclude(self, call):
        return self._add(
            NO_SLEEP,
            self.cfg.sleep_exclude,
            self.server_ids(call.ids),
            self.guild_label,
            after=self._wake_up,
        )

    async def _sleepinclude(self, call):
        return self._remove(NO_SLEEP, self.cfg.sleep_exclude, self.server_ids(call.ids), self.guild_label)

    async def _listchannels(self, call):
        listing = [self.channel_label(c) for c in sorted(self.cfg.channels)]
        return [f"**her channels ({len(listing)})**\n" + ("\n".join(listing) or "none")]

    async def _listusers(self, call):
        listing = [self.user_label(u) for u in sorted(self.cfg.ignored)]
        return [f"**ignored users ({len(listing)})**\n" + ("\n".join(listing) or "nobody")]

    async def _listsleep(self, call):
        return [self.app.away.listing(self.guild_label)]

    async def _sleep(self, call):
        nums = HOURS.findall(call.rest)
        hours = float(nums[0]) if nums else None
        out = []
        for gid in self.server_ids(call.ids):
            guild = self.messages.guild(gid)
            if guild is None:
                out.append(f"she isn't in `{gid}`")
                continue
            await self.app.sleep.go_away(guild, hours, why="told to", bye=False)
            out.append(f"asleep in {self.guild_label(gid)} for {self.app.away.sleep_left(gid) / 60:.1f}h")
        return out

    async def _wake(self, call):
        targets = self.server_ids(call.ids)
        if not call.ids and "all" in call.rest.lower():
            targets = [int(g) for g in list(self.app.away.data["sleep"])]
        if not targets:
            return [f"give me a server id, or `{call.cmd} all`"]
        return [f"{'woke up' if self.app.away.wake(g) else 'already awake'} in {self.guild_label(g)}" for g in targets]

    async def _reminders(self, call):
        store, low = self.app.reminders, call.rest.lower()
        if CANCEL_WORDS.search(low):
            gone = store.cancel(int(n) for n in SMALL_NUMBER.findall(call.rest))
            return ["\n".join(f"- #{r.id}: {r.what}" for r in gone) or "no such reminder"]
        if "clear" in low:
            return [f"cleared {len(store.cancel([r.id for r in store.items]))} reminders"]
        now = self.app.clock.now()
        rows = [
            f"#{r.id} {self.user_label(r.user)} {describe(datetime.fromtimestamp(r.due, now.tzinfo), now)}: {r.what}"
            for r in store.upcoming()
        ]
        return [f"**reminders ({len(rows)})**\n" + ("\n".join(rows) or "none")]

    async def _routine(self, call):
        if call.rest.strip().lower() in ("redo", "again", "new"):
            return [self.app.routine.redo()]
        return [self.app.routine.listing()]

    async def _busy(self, call):
        found = SMALL_NUMBER.search(call.rest)
        minutes = int(found.group(0)) if found else 30
        what = (call.rest[found.end() :] if found else call.rest).strip() or "busy"
        self.app.routine.set_busy(minutes, what)
        return [f"she's {what} for {minutes} min" if self.app.routine.on else "routine is off, `ROUTINE: true` first"]

    async def _free(self, call):
        found = SMALL_NUMBER.search(call.rest)
        minutes = int(found.group(0)) if found else 60
        self.app.routine.set_free(minutes)
        return [f"she's free for {minutes} min, whatever her plan says"]

    async def _stats(self, call):
        return [self.app.metrics.report(), self.state.stats(), f"{len(self.app.tasks)} background tasks running"]

    async def _help(self, call):
        return [help_text(self.cfg.COMMAND_PREFIX)]

    async def _prefix(self, call):
        new = call.rest.strip()
        if not new:
            return [f"the prefix is `{self.cfg.COMMAND_PREFIX}`, change it with `{call.cmd} <new>`"]
        problem = prefix_problem(new)
        if problem:
            return [problem]
        self.cfg.COMMAND_PREFIX = new
        self.cfg.save_value("COMMAND_PREFIX", new)
        return [f"the prefix is now `{new}`, like `{new}help`"]

    async def _forgetme(self, call):
        return [await self.app.privacy.forget_me(self.app.owner.id)]

    async def _rememberme(self, call):
        return [await self.app.privacy.remember_me(self.app.owner.id)]

    async def _quiet(self, call):
        args = call.rest.split()
        server = next((self.messages.guild(int(a)) for a in args if len(a) >= 15 and a.isdigit()), None)
        rest = [a for a in args if not (len(a) >= 15 and a.isdigit())]
        where = server.name if server is not None else "every server"
        if rest and rest[0].lower() in ("off", "0", "stop"):
            if server is None:
                self.app.away.unquiet_everywhere()
            else:
                self.app.away.unquiet(server.id)
            return [f"she can talk again in {where}"]
        mins = int(rest[0]) if rest and rest[0].isdigit() else 30
        self.app.away.quiet(server.id if server is not None else ALL, mins)
        return [f"completely quiet in {where} for {mins} min"]

    async def _orders(self, call):
        args, owner = call.rest.split(), self.app.owner
        verb = args[0].lower() if args else ""
        if verb == "add" and len(args) > 1:
            o = owner.add_order(" ".join(args[1:]))
            return [f"+ order {o['id']}: {o['text']}" if o else "she already has that one"]
        if verb in ("forget", "remove", "drop") and len(args) > 1:
            gone = owner.drop_orders(re.findall(r"\d+", " ".join(args[1:])))
            return ["\n".join(f"- order {o['id']}: {o['text']}" for o in gone) or "no such order"]
        if verb == "clear":
            owner.drop_orders([o["id"] for o in owner.data["orders"]])
            return ["all orders cleared"]
        listing = owner.orders_listing()
        return [f"**standing orders from {self.app.situation.owner_call()}**\n{listing or 'none'}"]
