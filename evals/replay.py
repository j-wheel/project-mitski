import argparse
import asyncio
import json
import random
import re
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import aiohttp
import yaml

from evals.judge import DIMENSIONS, Judge
from mitski.config.schema import SECTIONS
from mitski.core import logs
from mitski.paths import Paths
from mitski.testing.fakes import settle
from mitski.testing.world import QUIET_WORLD, build_world, instant_sleep

HERE = Path(__file__).resolve().parent
# who she is and how she writes, taken from config/mitski.yaml for live runs (the rest stays the quiet test world)
HERS = (
    "PERSONA",
    "IDENTITY_NOTE",
    "HER_AGE",
    "HER_GENDER",
    "HER_FROM",
    "HER_CITY",
    "PROMPT_FORMAT",
    "LORA_SCALE",
    "ANSWER_RETRY_LORA",
    "NAME_TRIGGERS",
    "TIMEZONE",
    "NOTES_PLACEMENT",
    "CONTEXT_MSGS",
    "STYLE_NOTE",
    "LOWERCASE",
    "NOTES_URL",
    "NOTES_MODEL",
)
LOW_SCORE = 3.5


@dataclass
class Case:
    name: str
    turns: list
    expect: dict
    config: dict = field(default_factory=dict)
    replies: list = field(default_factory=list)
    setup: dict = field(default_factory=dict)
    rubric: dict = field(default_factory=dict)
    judge: object = None

    @classmethod
    def from_json(cls, raw):
        return cls(
            name=raw["name"],
            turns=raw["turns"],
            expect=raw.get("expect", {}),
            config=raw.get("config", {}),
            replies=raw.get("replies", []),
            setup=raw.get("setup", {}),
            rubric=raw.get("rubric", {}),
            judge=raw.get("judge"),
        )


@dataclass
class Result:
    case: Case
    sent: list
    failures: list
    seconds: float
    llm_calls: int
    fallbacks: Counter = field(default_factory=Counter)
    scores: dict = field(default_factory=dict)
    chat: list = field(default_factory=list)

    @property
    def passed(self):
        return not self.failures

    @property
    def persona_score(self):
        return sum(s for s, _ in self.scores.values()) / len(self.scores) if self.scores else None


def her_settings(path=None):
    path = Path(path) if path else Paths.discover(create=False).config
    if not path.exists():
        return {}
    values = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    keep = set(HERS) | {o.key for s in SECTIONS if s.title.startswith("generation") for o in s.options}
    return {k: v for k, v in values.items() if k in keep and k not in QUIET_WORLD}


def load_cases(paths, only=None):
    cases = []
    for path in paths:
        for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                case = Case.from_json(json.loads(line))
            except (json.JSONDecodeError, KeyError) as e:
                raise SystemExit(f"{path}:{n}: {e}") from e
            if not only or re.search(only, case.name):
                cases.append(case)
    return cases


def check(expect, sent):
    text = "\n".join(sent).lower()
    failures = []
    if expect.get("silent") and sent:
        failures.append(f"expected silence, got {sent!r}")
    if expect.get("reply") and not sent:
        failures.append("expected a reply, got nothing")
    for needle in expect.get("contains", []):
        if needle.lower() not in text:
            failures.append(f"missing {needle!r}")
    for needle in expect.get("not_contains", []):
        if needle.lower() in text:
            failures.append(f"should not say {needle!r}")
    for pattern in expect.get("matches", []):
        if not re.search(pattern, text, re.I):
            failures.append(f"no match for /{pattern}/")
    limit = expect.get("max_messages")
    if limit is not None and len(sent) > limit:
        failures.append(f"sent {len(sent)} messages, limit {limit}")
    return failures


def prepare(world, setup):
    gid = world.guild.id
    if setup.get("quiet_minutes"):
        world.app.away.quiet(gid, setup["quiet_minutes"])
    if setup.get("asleep_hours"):
        world.app.away.sleep(gid, setup["asleep_hours"], "eval")
    for name in setup.get("ignored", []):
        world.app.cfg.ignored.add(world.person(name).id)


def too_low(expect, scores):
    failures = []
    for dim, least in (expect.get("min_scores") or {}).items():
        if dim in scores and scores[dim][0] < least:
            failures.append(f"{dim} scored {scores[dim][0]:.1f}, wants {least}")
    return failures


async def run_case(case, root, live, judge=None, base=None):
    random.seed(case.name)
    world = build_world(Paths(Path(root)), {**(base or {}), **case.config, **({"LLM_URL": live} if live else {})})
    prepare(world, case.setup)
    if not live:
        world.script()
        world.replies.extend(case.replies)
    else:
        world.app.http = aiohttp.ClientSession()
        await world.app.llm.probe()
    start, chat, scores = time.monotonic(), [], {}
    try:
        for turn in case.turns:
            author = world.person(turn.get("from", "anna"))
            seen = len(world.client.sent)
            await world.app.router.route(world.say(author, turn["text"], turn.get("to_her", True)))
            await settle(world.app, timeout=180)
            chat.append(f"{author.name}: {turn['text']}")
            chat += [f"{world.her.name}: {m.content}" for m in world.client.sent[seen:]]
        sent = world.sent_text()
        seconds = time.monotonic() - start
        if judge is not None:
            scores = await judge.score(world, chat, case.judge, case.rubric)
    finally:
        await world.app.tasks.cancel_all()
        if world.app.http is not None:
            await world.app.http.close()
    calls = sum(t.total_calls for t in world.app.metrics.done)
    fallbacks = Counter()
    for t in world.app.metrics.done:
        fallbacks.update(t.events)
    failures = check(case.expect, sent) + too_low(case.expect, scores)
    return Result(case, sent, failures, seconds, calls, fallbacks, scores, chat)


async def run(cases, live, judge=None, base=None):
    results = []
    with instant_sleep():
        for case in cases:
            with tempfile.TemporaryDirectory() as root:
                results.append(await run_case(case, root, live, judge, base))
    return results


def percentile(values, p):
    if not values:
        return 0.0
    values = sorted(values)
    k = (len(values) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def report(results, out=sys.stdout):
    width = max((len(r.case.name) for r in results), default=10)
    for r in results:
        mark = "pass" if r.passed else "FAIL"
        out.write(
            f"{mark}  {r.case.name:<{width}}  {r.seconds:5.1f}s  {r.llm_calls:2d} calls  {' | '.join(r.sent)[:80]}\n"
        )
        for f in r.failures:
            out.write(f"      - {f}\n")
        if r.fallbacks:
            out.write(f"      ~ {', '.join(f'{k} {v}' for k, v in sorted(r.fallbacks.items()))}\n")
        if r.scores:
            out.write(
                "      * "
                + " · ".join(f"{d} {r.scores[d][0]:.1f}" for d in DIMENSIONS if d in r.scores)
                + f" = {r.persona_score:.2f}\n"
            )
            for d in DIMENSIONS:
                if d in r.scores and r.scores[d][0] < LOW_SCORE and r.scores[d][1]:
                    out.write(f"        {d}: {r.scores[d][1][0][:220]}\n")
    passed = sum(r.passed for r in results)
    secs = [r.seconds for r in results]
    calls = [r.llm_calls for r in results]
    out.write(
        f"\n{passed}/{len(results)} passed · time p50 {percentile(secs, 50):.1f}s p95 {percentile(secs, 95):.1f}s"
        f" · llm calls p50 {percentile(calls, 50):.0f} p95 {percentile(calls, 95):.0f}\n"
    )
    fallbacks = Counter()
    for r in results:
        fallbacks.update(r.fallbacks)
    if fallbacks and results:
        rates = ", ".join(f"{k} {100 * v / len(results):.0f}%" for k, v in fallbacks.most_common())
        out.write(f"fallbacks per case: {rates}\n")
    means = dimension_means(rows_of(results))
    if means:
        out.write(
            "judged: "
            + " · ".join(f"{d} {means[d]:.2f}" for d in DIMENSIONS if d in means)
            + f" · persona score {means['persona']:.2f} over {means['cases']} cases\n"
        )
    return passed == len(results)


def rows_of(results):
    return [
        {
            "name": r.case.name,
            "passed": r.passed,
            "sent": r.sent,
            "failures": r.failures,
            "seconds": r.seconds,
            "llm_calls": r.llm_calls,
            "fallbacks": dict(r.fallbacks),
            "scores": {d: s for d, (s, _) in r.scores.items()},
            "why": {d: w for d, (_, w) in r.scores.items()},
            "chat": r.chat,
        }
        for r in results
    ]


def dimension_means(rows):
    judged = [r for r in rows if r.get("scores")]
    if not judged:
        return {}
    out = {}
    for d in DIMENSIONS:
        got = [r["scores"][d] for r in judged if d in r["scores"]]
        if got:
            out[d] = sum(got) / len(got)
    per_case = [sum(r["scores"].values()) / len(r["scores"]) for r in judged]
    out["persona"] = sum(per_case) / len(per_case)
    out["cases"] = len(judged)
    return out


def compare(old_rows, new_rows, out=sys.stdout):
    old = {r["name"]: r for r in old_rows}
    both = [r for r in new_rows if r["name"] in old]
    if not both:
        out.write("\nnothing to compare: no case names in common with the old results\n")
        return
    before = [old[r["name"]] for r in both]
    out.write(f"\ncompared with the old results ({len(both)} cases in both):\n")
    out.write(f"  passed {sum(r['passed'] for r in before)} -> {sum(r['passed'] for r in both)}\n")
    for label, of in (
        ("llm calls per case", lambda r: r["llm_calls"]),
        ("fallbacks per case", lambda r: sum(r["fallbacks"].values())),
    ):
        x, y = (sum(map(of, rows)) / len(rows) for rows in (before, both))
        out.write(f"  {label} {x:.2f} -> {y:.2f}\n")
    a, b = dimension_means(before), dimension_means(both)
    for d in (*DIMENSIONS, "persona"):
        if d in a and d in b:
            out.write(f"  {d} {a[d]:.2f} -> {b[d]:.2f} ({b[d] - a[d]:+.2f})\n")
    for r in both:
        o = old[r["name"]]
        if o["passed"] != r["passed"]:
            out.write(f"  {'now passes' if r['passed'] else 'now FAILS'}: {r['name']}\n")
        if o.get("scores") and r.get("scores"):
            x = sum(o["scores"].values()) / len(o["scores"])
            y = sum(r["scores"].values()) / len(r["scores"])
            if abs(y - x) >= 0.75:
                out.write(f"  {'better' if y > x else 'worse'} ({x:.2f} -> {y:.2f}): {r['name']}\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description="replay recorded conversations through her and check what she says")
    parser.add_argument("files", nargs="*", default=sorted(str(p) for p in (HERE / "cases").glob("*.jsonl")))
    parser.add_argument("--live", metavar="URL", help="use a running llama-server instead of the scripted replies")
    parser.add_argument("-k", dest="only", help="only run cases whose name matches this regex")
    parser.add_argument("--json", dest="json_out", help="also write the results to this file")
    parser.add_argument(
        "--judge",
        nargs="?",
        const="",
        metavar="URL",
        help="grade her replies with a rubric (voice, in character, fits, human, boundaries). no URL = her own "
        "model without the lora (needs --live), or an openai-compatible server, ideally a different model",
    )
    parser.add_argument("--judge-model", default="", help="model name to send to the judge server, if it wants one")
    parser.add_argument("--judge-runs", type=int, default=1, help="grade each case this many times and average")
    parser.add_argument(
        "--defaults",
        action="store_true",
        help="with --live, use the built-in persona instead of the one in mitski.yaml",
    )
    parser.add_argument("--compare", metavar="JSON", help="compare with results saved earlier with --json")
    args = parser.parse_args(argv)
    if args.judge == "" and not args.live:
        parser.error("--judge without a URL grades with her own model, so it needs --live")
    logs.setup("WARNING")
    judge = Judge(args.judge, args.judge_model, args.judge_runs) if args.judge is not None else None
    base = her_settings() if args.live and not args.defaults else {}
    if args.live:
        source = "the built-in persona" if args.defaults or not base else "her persona and settings from mitski.yaml"
        print(f"live at {args.live} with {source}" + (f", judged by {args.judge or 'her own model'}" if judge else ""))
    results = asyncio.run(run(load_cases(args.files, args.only), args.live, judge, base))
    ok = report(results)
    rows = rows_of(results)
    if args.compare:
        compare(json.loads(Path(args.compare).read_text(encoding="utf-8")), rows)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
