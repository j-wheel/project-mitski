import asyncio
import re
from dataclasses import dataclass, field, replace

from mitski.brain import prompts
from mitski.brain.answers import clean_brief
from mitski.brain.calc import calc
from mitski.chat.messages import short_name
from mitski.core import logs, voice
from mitski.core.collections import BoundedDict
from mitski.core.component import Component
from mitski.core.text import cut
from mitski.reminders.timing import HINT as REMINDER_HINT

log = logs.get("brain")

ASKED_TO_SEARCH = re.compile(r"\b(google|search|look (it|that|this|them|him|her) up|look up|check online|wiki)\b", re.I)
CURRENT_STUFF = re.compile(
    r"\b(latest|newest|news|patch|patch notes|update|release date|released|come out|coming out|"
    r"trailer|announced|who won|winner|standings|price|prices|cost|tickets|on tour|new season|"
    r"new album|new episode)\b",
    re.I,
)
TRIVIAL = re.compile(r"^\W*(?:\w+\W*){0,3}$")

WORTH = re.compile(
    r"\?|\b(what|whats|what's|who|whos|who's|when|where|which|why|how|is it|are there|does|do you know|can you|could you|"
    r"tell me|explain|describe|look at|see this|check this|thoughts|opinion|rate|google|search|look (it |that )?up|"
    r"weather|temperature|forecast|rain|snow|time is it|what time|calculate|solve|math|translate|meaning|means|"
    r"news|latest|update|patch|release|score|won|price|cost|recommend|remind|reminder)\b|\d\s*[-+*/x^]\s*\d",
    re.I,
)


@dataclass
class Thought:
    notes: list = field(default_factory=list)
    to_her: str | None = "her"
    reply_type: str = ""
    brief: str = ""
    wants: str = ""
    actions: dict = field(default_factory=dict)
    checked: bool = False
    topics: list | None = None
    length: str = "short"

    def __post_init__(self):
        self.notes = [n for n in self.notes if n]
        self.actions = self.actions or {}

    @property
    def wants_answer(self):
        return self.reply_type in prompts.ANSWERY and bool(self.brief)

    def without_plan(self):
        return replace(self, brief="", wants="")


@dataclass
class Question:
    target: object
    msgs: list
    channel: object
    her: str
    name: str
    newest: str
    parts: list
    several: bool
    remind: bool
    explicit: bool
    to_her: str | None
    owner: bool
    orders: str
    recent: str
    about: str


def search_query(text, her):
    query = re.sub(
        r"@\S+|\b(?:mitski|" + re.escape(her) + r"|google|search|look (?:it|that|this) up|look up|"
        r"(?:can|could|will|would) (?:you|u|ya)|pls|plz|please|hey|yo|for me)\b|[?!]+",
        " ",
        text,
        flags=re.I,
    )
    return re.sub(r"\s+", " ", query).strip(" ,.")[:100]


class Brain(Component):
    def __init__(self, app):
        super().__init__(app)
        self.done = BoundedDict(500)

    @property
    def enabled(self):
        return self.cfg.THINKING

    @property
    def always(self):
        return self.cfg.THINK_ALWAYS

    def worth_it(self, mode, target, explicit=True, said=None):
        if not self.enabled or target is None:
            return False
        if not explicit:
            return True
        text = said or self.messages.text(target)
        if "?" not in text and TRIVIAL.match(text) and not WORTH.search(text):
            return False
        if self.always and mode in ("direct", "dm"):
            return True
        return bool(WORTH.search(text)) and (mode in ("direct", "dm") or "?" in text)

    async def think(
        self,
        mode,
        target,
        msgs,
        explicit=True,
        channel=None,
        to_her=None,
        owner=False,
        orders="",
        said=None,
        parts=None,
    ):
        if not (self.worth_it(mode, target, explicit, said) or (owner and self.enabled and target is not None)):
            return Thought()
        if target.id in self.done:
            return self.done[target.id]
        q = self._question(target, msgs, channel, explicit, to_her, owner, orders, said, parts)
        thought = await self._plan(q)
        self.done[target.id] = thought
        return thought

    def _question(self, target, msgs, channel, explicit, to_her, owner, orders, said, parts):
        newest = said or self.messages.text(target)
        return Question(
            target=target,
            msgs=list(msgs),
            channel=channel,
            her=short_name(self.me),
            name=self.memory.call_name(target.author) or short_name(target.author),
            newest=newest,
            parts=[p for p in (parts or []) if p],
            several=bool(said) and said != self.messages.text(target),
            remind=bool(REMINDER_HINT.search(newest)),
            explicit=explicit,
            to_her=to_her,
            owner=owner,
            orders=orders,
            recent=self._recent_chat(msgs),
            about=self._replying_to(target),
        )

    def _who_is(self, user):
        return short_name(self.me) if user.id == self.me.id else (self.memory.call_name(user) or short_name(user))

    def _recent_chat(self, msgs):
        by_id = {m.id: m for m in msgs}
        return "\n".join(self._line_for(m, by_id) for m in list(msgs)[-12:])

    def _line_for(self, m, by_id):
        ref = getattr(m, "reference", None)
        parent = by_id.get(ref.message_id) if ref and getattr(ref, "message_id", None) else None
        if parent is None and ref is not None and hasattr(getattr(ref, "resolved", None), "author"):
            parent = ref.resolved
        to = ""
        if parent is not None and parent.author.id != m.author.id:
            to = f" (replying to {self._who_is(parent.author)})"
        elif m.author.id == self.me.id and self.state.addressed.get(m.id):
            who = self.messages.name_of_id(self.state.addressed[m.id])
            to = f" (to {who})" if who else ""
        return f"{self._who_is(m.author)}{to}: {cut(self.messages.text(m), 220)}"

    def _replying_to(self, target):
        ref = target.reference.resolved if getattr(target, "reference", None) else None
        if ref is None or not hasattr(ref, "author"):
            return ""
        who = (
            "her" if ref.author.id == self.me.id else f"{self.memory.call_name(ref.author) or short_name(ref.author)}'s"
        )
        return f'\n(it\'s a discord reply to {who} message: "{cut(self.messages.text(ref), 200)}")'

    def _in_her_voice(self, q, brief):
        names = self.messages.own_names()
        others = {self.messages.call(m.author) for m in q.msgs if m.author.id != self.me.id}
        she_too = voice.opens_with_she(brief) and voice.asked_about_her(q.newest, others)
        return voice.to_first_person(brief, names, she_too=she_too)

    def _tools(self, channel):
        return prompts.available_tools(
            search=bool(self.app.search.provider),
            weather=self.cfg.WEATHER,
            vision=self.app.vision.active,
            history=bool(channel),
        )

    async def _plan(self, q):
        tools = self._tools(q.channel)
        system, user, schema, budget = prompts.plan_request(q, tools, self.app.clock.now())
        plan = await self.app.helper.ask_json(system, user, schema, budget)
        if not plan:
            return Thought()
        to_her = q.to_her or (
            plan.get("to_her") if plan.get("to_her") in ("her", "someone_else", "everyone") else "her"
        )
        reply_type = plan.get("reply_type") if plan.get("reply_type") in prompts.REPLY_TYPES else "other"
        length = plan.get("length") if plan.get("length") in prompts.LENGTHS else "short"
        wants = voice.to_you(cut(str(plan.get("wants") or "").strip(), 160), self.messages.own_names())
        answer = cut(str(plan.get("answer") or "").strip(), 300)
        if not q.explicit and to_her == "someone_else":
            log.info("%s: not for her (%s)", q.name, wants or "talking to someone else")
            return Thought(to_her=to_her, reply_type=reply_type, wants=wants)
        steps = self._steps(plan, tools)
        if self._should_search(q, tools, steps, reply_type):
            query = search_query(q.newest, q.her)
            if len(query) >= 3:
                steps.append({"tool": "search", "input": query})
                answer = ""
        results = await asyncio.gather(
            *(self.run(s["tool"], str(s["input"]).strip(), q.target, q.msgs, q.name, q.channel) for s in steps),
            return_exceptions=True,
        )
        checked = [r for r in results if isinstance(r, str) and r]
        failed = [s["tool"] for s, r in zip(steps, results, strict=True) if not (isinstance(r, str) and r)]
        brief = clean_brief(answer)
        if checked and reply_type in prompts.ANSWERY:
            out = await self.app.helper.ask_json(*prompts.brief_request(q, checked, answer))
            brief = clean_brief((out or {}).get("say")) or brief
        brief = self._in_her_voice(q, brief)
        notes = self._notes(q, to_her, reply_type, wants, brief, checked, failed)
        actions = self._actions(q, plan)
        await self._report(
            q,
            plan,
            to_her,
            f"{reply_type}, longer" if length == "longer" else reply_type,
            wants,
            brief,
            steps,
            checked,
            actions,
        )
        return Thought(
            notes,
            to_her,
            reply_type,
            brief if reply_type in prompts.ANSWERY else "",
            wants,
            actions,
            checked=bool(checked),
            topics=self._topics(q, plan),
            length=length,
        )

    @staticmethod
    def _steps(plan, tools):
        steps = [
            s
            for s in plan.get("tools") or []
            if isinstance(s, dict) and s.get("tool") in tools and str(s.get("input") or "").strip()
        ]
        return steps[:3]

    @staticmethod
    def _should_search(q, tools, steps, reply_type):
        if "search" not in tools or len(steps) >= 3 or any(s["tool"] == "search" for s in steps):
            return False
        text = q.newest
        return bool(ASKED_TO_SEARCH.search(text) or (reply_type == "answer_question" and CURRENT_STUFF.search(text)))

    @staticmethod
    def _notes(q, to_her, reply_type, wants, brief, checked, failed):
        notes = [f"What {q.name} wants: {wants.rstrip('.')}."] if wants else []
        notes += checked
        if failed and not checked and reply_type == "answer_question" and not brief:
            notes.append("You tried to check but couldn't find out, so say you're not sure instead of guessing.")
        if brief and reply_type in prompts.ANSWERY:
            notes.append(prompts.ANSWER_NOTE.format(brief=brief.rstrip(".")))
        elif prompts.REPLY_TYPES.get(reply_type):
            notes.append(prompts.REPLY_TYPES[reply_type])
        if to_her == "everyone" and not q.explicit:
            notes.append(f"{q.name} said that to the whole chat, not just you.")
        if q.owner:
            notes.append(f"If {q.name} is asking you to do something, just do it.")
        return notes

    @staticmethod
    def _actions(q, plan):
        actions = {}
        r = plan.get("remind") if q.remind else None
        if isinstance(r, dict) and str(r.get("what") or "").strip():
            actions["remind"] = {k: r.get(k) for k in prompts.REMIND["properties"]}
            actions["remind"]["said"] = q.newest
        if not q.owner:
            return actions
        for k in ("order", "status", "dm_who", "dm_say"):
            v = cut(str(plan.get(k) or "").strip(), 300)
            if v:
                actions[k] = v
        if plan.get("drop_orders"):
            actions["drop_orders"] = [int(i) for i in plan["drop_orders"] if str(i).lstrip("-").isdigit()]
        quiet = plan.get("quiet_minutes")
        if isinstance(quiet, int) and quiet != 0:
            actions["quiet_minutes"] = quiet
        return actions

    @staticmethod
    def _topics(q, plan):
        if len(q.parts) < 2 or not isinstance(plan.get("topics"), list):
            return None
        return sorted({int(t) for t in plan["topics"] if isinstance(t, int) and 1 <= t <= len(q.parts)}) or None

    async def _report(self, q, plan, to_her, reply_type, wants, brief, steps, checked, actions):
        log.info(
            "%s: %s (to %s) | %s%s%s%s%s",
            q.name,
            reply_type,
            to_her,
            ", ".join(f"{s['tool']}({s['input']})" for s in steps),
            f" | wants: {wants}" if wants else "",
            f" | answer: {brief}" if brief else "",
            f" | do: {actions}" if actions else "",
            f" | separate things: {plan.get('topics')}" if len(q.parts) >= 2 else "",
        )
        if steps or brief:
            await self.app.relay.post(
                f"**thought about {q.name}'s message** ({reply_type}, to {to_her})\n"
                + "".join(f"- {s['tool']}: `{cut(s['input'], 80)}`\n" for s in steps)
                + "".join(f"> {cut(c, 300)}\n" for c in checked)
                + (f"**will say:** {brief}" if brief else "")
            )

    async def run(self, tool, arg, target, msgs, name, channel=None):
        try:
            if tool == "history":
                return await self.app.tools.history(arg, channel, msgs)
            if tool == "search":
                return await self.app.search.answer(arg, self.messages.text(target), name)
            if tool == "weather":
                return await self.app.tools.weather(arg)
            if tool == "time":
                return await self.app.tools.time_in(arg)
            if tool == "calc":
                out = calc(arg)
                return f"You worked it out: {out}." if out else ""
            if tool == "look_closer":
                candidates = [target]
                ref = target.reference.resolved if getattr(target, "reference", None) else None
                if ref is not None and hasattr(ref, "attachments"):
                    candidates.append(ref)
                candidates += list(reversed(list(msgs)))
                text = await self.app.vision.detail(candidates, arg or self.messages.text(target))
                return f"You looked at it closely: {text}" if text else ""
            if tool == "recall":
                return self.app.tools.recall(arg, skip_id=target.author.id)
            if tool == "remember":
                return await self.memory.remember(target.author, arg)
        except Exception:
            log.warning("%s(%r) failed", tool, arg, exc_info=True)
        return ""
