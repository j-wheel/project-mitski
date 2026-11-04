import re

from mitski.chat.patterns import NO_PINGS
from mitski.core import logs
from mitski.core.text import cut
from mitski.memory.heuristics import IDS, norm_slot
from mitski.memory.schema import SLOTS

log = logs.get("memory")


class CommandsMixin:
    async def command(self, msg):
        text = msg.content.strip()
        cmd = text.split(maxsplit=1)[0].lower() if text else ""
        if cmd not in ("!mem", "!forget", "!note", "!set"):
            return False
        if self.admins and msg.author.id not in self.admins:
            return True
        args = text.split()[1:]
        reply = (
            "usage: `!mem <who>` · `!mem self` · `!mem update <who>` · `!mem reflect <who>` · `!mem raw <who>` · "
            "`!mem search <who> <what>` · `!forget <who> <F3|E2|T1|S3|age|nickname|portrait|jokes|all>` · "
            "`!note <who> [cat] <fact>` · `!set <who> <field> <value>`"
        )
        changes = []
        if cmd == "!mem" and len(args) >= 3 and args[0].lower() == "search":
            uid, d = self.find_person(args[1])
            if d is None:
                reply = f"don't know anyone called `{args[1]}`"
            else:
                hits = await self.search(d, " ".join(args[2:]), 6)
                call = self.call_name(d) or d["name"]
                reply = f"**{d['name']}** · {self.embed.status()}\n" + (
                    "\n".join(f"- {kind}: {self._line(d, kind, obj, call)}" for kind, obj in hits) or "nothing fits"
                )
        elif cmd == "!mem" and len(args) >= 2 and args[0].lower() == "reflect":
            uid, d = self.find_person(" ".join(args[1:]))
            if d is None:
                reply = f"don't know anyone called `{' '.join(args[1:])}`"
            else:
                changes = await self.reflect(d, d["name"])
                reply = "\n".join(changes) or "nothing changed"
        elif cmd == "!mem" and len(args) >= 2 and args[0].lower() in ("update", "raw"):
            uid, d = self.find_person(" ".join(args[1:]))
            if d is None:
                reply = f"don't know anyone called `{' '.join(args[1:])}`"
            elif args[0].lower() == "raw":
                raw = self.last_raw.get(int(uid))
                reply = (
                    f"last thing the notes model wrote about {d['name']}:\n```\n{cut(raw, 1800)}\n```"
                    if raw
                    else f"no update for {d['name']} since the bot started"
                )
            else:
                user, channel = self.last_user.get(int(uid)), self.last_channel.get(int(uid))
                if user is None or channel is None:
                    reply = f"haven't seen {d['name']} talk since the bot started, can't read their chat yet"
                else:
                    self.running.add(user.id)
                    await self.update(user, channel)
                    reply = self.describe(self.get(uid))
        elif args and args[0].lower() == "self":
            if cmd == "!mem":
                reply = "**what she's said about herself**\n" + (
                    "\n".join(f"`S{f['id']}` [{f['cat']}] {f['text']}" for f in self.own["facts"]) or "nothing yet"
                )
            elif cmd == "!forget" and len(args) > 1:
                for _p, i in IDS.findall(" ".join(args[1:])):
                    self._forget_fact(self.own, int(i), changes, "S", "by hand")
                reply = "\n".join(changes) or "no such S number"
            elif cmd == "!note" and len(args) > 1:
                cat = args[1].strip("[]") if args[1].startswith("[") else "other"
                fact = " ".join(args[2:] if args[1].startswith("[") else args[1:])
                self._add_fact(self.own, fact, cat, "said", None, changes, "S")
                reply = "\n".join(changes) or "she already knows that"
        elif args:
            uid, d = self.find_person(args[0])
            if d is None:
                reply = f"don't know anyone called `{args[0]}`"
            elif cmd == "!mem":
                reply = self.describe(d)
            elif cmd == "!forget" and len(args) > 1:
                what = args[1].lower()
                if what == "all":
                    del self.people[uid]
                    changes.append(f"forgot everything about {d['name']}")
                elif norm_slot(what) and norm_slot(what) in d["slots"]:
                    changes.append(f"- {norm_slot(what)}: {self._slot_value(d, norm_slot(what))}")
                    del d["slots"][norm_slot(what)]
                elif what in ("bond", "portrait", "talk_style", "history", "jokes", "avoid", "shared"):
                    d.pop(what, None)
                    changes.append(f"- {what}")
                else:
                    rest = " ".join(args[1:])
                    for _p, i in IDS.findall(rest):
                        self._forget_fact(d, int(i), changes, "F", "by hand")
                    for kind, key in (("E", "episodes"), ("T", "threads")):
                        for i in re.findall(kind + r"\s*(\d+)", rest, re.I):
                            hit = next((x for x in d.get(key, []) if x["id"] == int(i)), None)
                            if hit is not None:
                                d[key].remove(hit)
                                changes.append(f"- {kind}{i} {hit.get('summary') or hit.get('text')}")
                reply = "\n".join(changes) or "nothing to forget there"
            elif cmd == "!note" and len(args) > 1:
                rest = args[1:]
                cat = rest[0].strip("[]") if rest[0].startswith("[") else "other"
                fact = " ".join(rest[1:] if rest[0].startswith("[") else rest)
                self._add_fact(d, fact, cat, "said", None, changes, "F", self._names_of(d))
                reply = "\n".join(changes) or "she already knows that"
            elif cmd == "!set" and len(args) > 2 and args[1].lower() in ("rel", "pinned"):
                value = " ".join(args[2:]).strip()
                if value == "-":
                    d.pop(args[1].lower(), None)
                    changes.append(f"- {args[1].lower()}")
                else:
                    d[args[1].lower()] = value[:600]
                    changes.append(f"+ {args[1].lower()}: {value[:600]}")
                reply = "\n".join(changes)
            elif cmd == "!set" and len(args) > 2:
                key = norm_slot(args[1])
                if key:
                    self._set_slot(d, key, " ".join(args[2:]), "her" if key == "her_nick" else "said", changes)
                    reply = "\n".join(changes) or "already that"
                else:
                    reply = f"fields: {', '.join(list(SLOTS) + ['her_nick', 'rel', 'pinned'])}"
        if changes:
            self.dirty = True
        for i in range(0, min(len(reply), 5700), 1900):
            await msg.channel.send(reply[i : i + 1900], allowed_mentions=NO_PINGS)
        return True
