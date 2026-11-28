import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime

import discord
import yaml

from mitski.admin import printchat
from mitski.admin.registry import help_text, parse
from mitski.chat.policy import ABOUT_MODES, MODES
from mitski.config import ConfigError, prefix_problem
from mitski.core import logs
from mitski.core.component import Component
from mitski.reminders.timing import describe
from mitski.social.away import ALL
from mitski.social.feelings import BOUNDS, EVENTS_KEPT, fresh_regard

log = logs.get("commands")

CHUNK = 1900
HOURS = re.compile(r"(?<![\d.])(\d{1,2}(?:\.\d+)?)(?![\d.])")
SMALL_NUMBER = re.compile(r"(?<!\d)\d{1,6}(?!\d)")
CANCEL_WORDS = re.compile(r"\b(?:cancel|remove|delete|forget)\b")
MEMORY_COMMANDS = {"mem", "forget", "note", "set"}
EXPORT_FLAG = re.compile(r"(?:^|\s)--(png|pdf)(?=\s|$)", re.I)
MODE_WORD = re.compile(rf"\b({'|'.join(MODES)})\b", re.I)
HAND_SET = {"like": "like", "trust": "trust", "chemistry": "spark", "spark": "spark", "hurt": "hurt"}


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
MUTED = LiveList("MUTED_CHANNELS", "+ muted in {}", "already muted in {}", "- unmuted in {}", "wasn't muted in {}")
AMODS = LiveList(
    "AMOD",
    "+ {} can use mute and unmute",
    "{} already can use mute and unmute",
    "- {} can't use mute and unmute anymore",
    "{} wasn't an amod",
)
MUTE_COMMANDS = {"mute", "unmute"}
NEEDS_IDS = {
    "block",
    "unblock",
    "addchannel",
    "delchannel",
    "ignoreuser",
    "unignoreuser",
    "sleepexclude",
    "sleepinclude",
    "sleep",
    "addp",
    "delp",
}


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

    def can_mute(self, msg):
        author, amod = msg.author, self.cfg.amod
        return (
            self.app.owner.is_owner(author)
            or author.id in amod
            or any(role.id in amod for role in getattr(author, "roles", None) or ())
        )

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

    def amod_label(self, i):
        for guild in self.app.guilds:
            role = guild.get_role(i)
            if role is not None:
                return f"role @{role.name} `{i}` ({guild.name})"
        return self.user_label(i)

    def server_ids(self, ids):
        return list(dict.fromkeys(getattr(self.messages.guild(i), "id", i) for i in ids))

    def forget_user(self, uid):
        self.state.forget_user(uid)
        return self.memory.people.pop(str(uid), None) is not None

    async def dispatch(self, msg):
        call = parse(msg.content, self.cfg.COMMAND_PREFIX)
        if call is None:
            return False
        call.channel = msg.channel
        if self.can_mute(msg) if call.name in MUTE_COMMANDS else self.can_use(msg):
            await self._run(call, msg.channel)
        return True

    async def _run(self, call, channel):
        if call.name in MEMORY_COMMANDS:
            await self.memory.command(channel, call.name, call.rest.split())
            return
        if call.name == "printchat":
            await self._printchat(call, channel)
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

    def _left(self, channel):
        self.state.forget_channel(channel.id)
        if self.app.voice.where(channel.guild) == channel:
            self.app.tasks.spawn(self.app.voice.leave("muted"), name="voice-leave")

    async def _mute(self, call):
        channel = call.channel
        if getattr(channel, "guild", None) is None:
            return ["that only works in server channels"]
        return self._add(MUTED, self.cfg.muted, [channel.id], self.channel_label, after=lambda _: self._left(channel))

    async def _unmute(self, call):
        channel = call.channel
        if getattr(channel, "guild", None) is None:
            return ["that only works in server channels"]
        return self._remove(MUTED, self.cfg.muted, [channel.id], self.channel_label)

    async def _modeset(self, call):
        word = MODE_WORD.search(call.rest)
        if word is None or not call.ids:
            return [f"usage: `{self.cfg.COMMAND_PREFIX}modeset <{'|'.join(MODES)}> <server id ...>`"]
        mode, out = word.group(1).lower(), []
        for gid in self.server_ids(call.ids):
            if self.messages.guild(gid) is None:
                out.append(f"she isn't in `{gid}`")
                continue
            self.app.policy.set_mode(gid, mode)
            out.append(f"{self.guild_label(gid)} is now **{mode}**")
        return out

    async def _mode(self, call):
        guild = self.messages.guild(call.ids[0]) if call.ids else getattr(call.channel, "guild", None)
        if guild is None:
            return ["give me a server id, dms don't have a mode" if not call.ids else f"she isn't in `{call.ids[0]}`"]
        mode = self.app.policy.mode_in(guild)
        return [f"{self.guild_label(guild.id)} is **{mode}**: {ABOUT_MODES[mode]}"]

    async def _modes(self, call):
        policy = self.app.policy
        about = "\n".join(f"**{m}**: {ABOUT_MODES[m]}" for m in MODES)
        servers = "\n".join(
            f"{policy.mode_in(g)} · {self.guild_label(g.id)}" for g in sorted(self.app.guilds, key=lambda g: g.name)
        )
        return [f"{about}\n\n**servers**\n{servers or 'none'}\n-# dms aren't part of this"]

    async def _addp(self, call):
        return self._add(AMODS, self.cfg.amod, call.ids, self.amod_label)

    async def _delp(self, call):
        return self._remove(AMODS, self.cfg.amod, call.ids, self.amod_label)

    async def _listp(self, call):
        listing = [self.amod_label(i) for i in sorted(self.cfg.amod)]
        return [f"**amods ({len(listing)})**\n" + ("\n".join(listing) or "nobody")]

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

    async def _block(self, call):
        out = []
        for uid in call.ids:
            user = self.app.get_user(uid) or self.app.client.get_user(uid)
            if user is None:
                try:
                    user = await self.app.client.fetch_user(uid)
                except discord.HTTPException as e:
                    out.append(f"couldn't find `{uid}`: {e}")
                    continue
            out.append(await self.app.blocking.block(user, "told to with !block", delay=False))
        return out

    async def _unblock(self, call):
        return [await self.app.blocking.unblock(uid) for uid in call.ids]

    async def _blocked(self, call):
        listing = [self.user_label(u) for u in sorted(self.app.blocking.blocked)]
        return [f"**blocked ({len(listing)})**\n" + ("\n".join(listing) or "nobody")]

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

    async def _printchat(self, call, channel):
        flag = EXPORT_FLAG.search(call.rest)
        kind = flag.group(1).lower() if flag else "pdf"
        who = EXPORT_FLAG.sub(" ", call.rest).strip()
        if not who:
            await self.reply(
                channel, f"usage: `{self.cfg.COMMAND_PREFIX}printchat [--png|--pdf] <user or dm channel id>`"
            )
            return
        target = await self._dm_for(call, who)
        if target is None:
            await self.reply(channel, f"she doesn't have a dm with `{who}`")
            return
        browser = printchat.find_browser(self.cfg.PRINTCHAT_BROWSER)
        if browser is None:
            await self.reply(channel, "no chrome or edge found to print it with, set `PRINTCHAT_BROWSER` to one")
            return
        title, _, slug = printchat.describe(target, self.me)
        await self.reply(channel, f"printing the dm {title}, this can take a minute..")
        with tempfile.TemporaryDirectory(prefix="printchat-", ignore_cleanup_errors=True) as tmp:
            try:
                out, count, pictures = await printchat.make(self.app, target, tmp, browser, kind)
            except (RuntimeError, OSError, discord.HTTPException) as e:
                log.warning("printchat failed", exc_info=True)
                await self.reply(channel, f"couldn't print it: {e}")
                return
            safe = re.sub(r"[^\w-]+", "-", slug).strip("-") or "chat"
            name = f"dm-{safe}-{self.app.clock.now():%Y-%m-%d}.{kind}"
            size = f"{out.stat().st_size / 1024 / 1024:.1f} MB"
            if pictures is None:
                keep = self.cfg.paths.data_file("exports") / name
                keep.parent.mkdir(parents=True, exist_ok=True)
                keep.write_bytes(out.read_bytes())
                await self.reply(
                    channel, f"it's {size}, too big for discord even without pictures. saved it to `{keep}`"
                )
                return
            note = f"{count} messages, {size}" + ("" if pictures else ", without pictures (too big with them)")
            sent = await channel.send(
                note, file=discord.File(str(out), filename=name), allowed_mentions=discord.AllowedMentions.none()
            )
            self.state.command_replies.add(sent.id)
        log.info("printed the dm %s: %s", title, note)

    async def _dm_for(self, call, text):
        for i in call.ids:
            found = self.app.get_channel(i)
            if isinstance(found, (discord.DMChannel, discord.GroupChannel)):
                return found
            user = self.app.get_user(i)
            if user is None:
                try:
                    user = await self.app.fetch_user(i)
                except discord.HTTPException:
                    continue
            return user.dm_channel or await user.create_dm()
        if call.ids:
            return None
        who = text.lstrip("@").lower()
        dms = [c for c in getattr(self.app.client, "private_channels", None) or [] if isinstance(c, discord.DMChannel)]

        def names(c):
            u = c.recipient
            return {
                str(n).lower() for n in (u.name, getattr(u, "display_name", ""), getattr(u, "global_name", "")) if n
            }

        for match in (lambda c: who in names(c), lambda c: any(n.startswith(who) for n in names(c))):
            found = next((c for c in dms if match(c)), None)
            if found is not None:
                return found
        uid, _ = self.memory.find_person(who)
        user = self.app.get_user(int(uid)) if uid else None
        return (user.dm_channel or await user.create_dm()) if user is not None else None

    async def _mood(self, call):
        return [self.app.feelings.report()]

    async def _feel(self, call):
        words = call.rest.split()
        if not words:
            return [f"usage: `{self.cfg.COMMAND_PREFIX}feel <who> [reset | like/trust/chemistry/hurt <number>]`"]
        uid, d = self.memory.find_person(words[0])
        if d is None:
            return [f"she doesn't know anyone called {words[0]}"]
        feelings, rest = self.app.feelings, [w.lower() for w in words[1:]]
        out = []
        if rest[:1] == ["reset"]:
            d["regard"] = fresh_regard()
            out.append("reset: back to neutral, like she just met them")
        elif len(rest) >= 2 and rest[0] in HAND_SET and re.fullmatch(r"-?\d+(\.\d+)?", rest[1]):
            dim = HAND_SET[rest[0]]
            r = feelings.regard(d)
            low, high = BOUNDS[dim]
            before = r[dim]
            r[dim] = max(low, min(high, float(rest[1])))
            if dim == "hurt":
                r["hurt_t"], r["hurt_why"] = time.time(), "set by hand"
            r["events"] = (
                r.get("events", [])
                + [{"t": time.time(), "kind": "set_by_hand", "i": 1, "d": {dim: r[dim] - before}, "src": "hand"}]
            )[-EVENTS_KEPT:]
            out.append(f"{rest[0]} set to {r[dim]:g}")
        self.memory.dirty = True
        return [*out, feelings.describe_person(d, int(uid))]

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
        return [
            self.app.metrics.report(),
            self.state.stats(),
            self.llm.cache_report(),
            self.app.downtime.report(),
            f"{len(self.app.tasks)} background tasks running",
        ]

    async def _help(self, call):
        return [help_text(self.cfg.COMMAND_PREFIX)]

    async def _reload(self, call):
        log.info("reloading (%s)", call.cmd)
        self.app.reload_soon()
        return ["reloading, back in a few seconds"]

    async def _profile(self, call):
        me = self.app.self_profile
        if call.rest.strip().lower() in ("refresh", "r", "now"):
            await me.refresh()
        note = me.note()
        return me.report() + ([f"-# what she's told: {note}"] if note else ["-# she hasn't read her profile yet"])

    async def _pfp(self, call):
        me = self.app.self_profile
        word, _, rest = call.rest.strip().partition(" ")
        word, rest = word.lower(), rest.strip()
        if not word:
            return me.report()
        if word in ("now", "change", "new", "next"):
            await self.reply(
                call.channel, f"looking for a new picture of {me.character[0] or '...'}, give her a minute"
            )
            return [await me.change("asked to", forced=True)]
        if word in ("char", "character"):
            name, bar, source = rest.partition("|")
            name, source = name.strip(), source.strip()
            if not name:
                return [f"like `{call.cmd} char onikata kayoko | blue archive`"]
            self.cfg.AVATAR_CHARACTER_NAME = name
            self.cfg.save_value("AVATAR_CHARACTER_NAME", name)
            if bar:
                self.cfg.AVATAR_CHARACTER_SOURCE = source
                self.cfg.save_value("AVATAR_CHARACTER_SOURCE", source)
            got_name, got_source = me.character
            return [f"her profile pictures will be {got_name}" + (f" from {got_source}" if got_source else "")]
        if word == "every":
            try:
                hours = [float(x) for x in rest.replace(",", " ").split()[:2]]
            except ValueError:
                hours = []
            if not hours or min(hours) < 0.5:
                return [f"like `{call.cmd} every 48` or `{call.cmd} every 24 72` (hours, at least 0.5)"]
            value = [hours[0], hours[0]] if len(hours) == 1 else sorted(hours)
            value = [int(h) if h == int(h) else h for h in value]
            self.cfg.AVATAR_EVERY_H = value
            self.cfg.save_value("AVATAR_EVERY_H", value)
            me.schedule()
            return [
                f"she'll change it every {value[0]:g}"
                + (f" to {value[1]:g}" if value[1] != value[0] else "")
                + " hours"
            ]
        if word in ("on", "off"):
            self.cfg.AVATAR_AUTO = word == "on"
            self.cfg.save_value("AVATAR_AUTO", word == "on")
            if word == "on":
                me.schedule()
            return [f"changing her profile picture by herself is {word}"]
        if word == "from" and rest.lower() in ("search", "danbooru"):
            self.cfg.AVATAR_FROM = rest.lower()
            self.cfg.save_value("AVATAR_FROM", rest.lower())
            return [f"her profile pictures come from {rest.lower()} now"]
        return [f"`{call.cmd} [now | char <name> | <from> | every <h> [max h] | on | off | from search|danbooru]`"]

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
