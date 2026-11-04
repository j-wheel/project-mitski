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

from mitski.core import logs
from mitski.paths import Paths
from mitski.testing.fakes import settle
from mitski.testing.world import build_world, instant_sleep

HERE = Path(__file__).resolve().parent


@dataclass
class Case:
    name: str
    turns: list
    expect: dict
    config: dict = field(default_factory=dict)
    replies: list = field(default_factory=list)
    setup: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, raw):
        return cls(
            name=raw["name"],
            turns=raw["turns"],
            expect=raw.get("expect", {}),
            config=raw.get("config", {}),
            replies=raw.get("replies", []),
            setup=raw.get("setup", {}),
        )


@dataclass
class Result:
    case: Case
    sent: list
    failures: list
    seconds: float
    llm_calls: int
    fallbacks: Counter = field(default_factory=Counter)

    @property
    def passed(self):
        return not self.failures


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


async def run_case(case, root, live):
    random.seed(case.name)
    world = build_world(Paths(Path(root)), {**case.config, **({"LLM_URL": live} if live else {})})
    prepare(world, case.setup)
    if not live:
        world.script()
        world.replies.extend(case.replies)
    else:
        world.app.http = aiohttp.ClientSession()
        await world.app.llm.probe()
    start = time.monotonic()
    try:
        for turn in case.turns:
            author = world.person(turn.get("from", "anna"))
            await world.app.router.route(world.say(author, turn["text"], turn.get("to_her", True)))
            await settle(world.app, timeout=180)
        sent = world.sent_text()
    finally:
        await world.app.tasks.cancel_all()
        if world.app.http is not None:
            await world.app.http.close()
    calls = sum(t.total_calls for t in world.app.metrics.done)
    fallbacks = Counter()
    for t in world.app.metrics.done:
        fallbacks.update(t.events)
    return Result(case, sent, check(case.expect, sent), time.monotonic() - start, calls, fallbacks)


async def run(cases, live):
    results = []
    with instant_sleep():
        for case in cases:
            with tempfile.TemporaryDirectory() as root:
                results.append(await run_case(case, root, live))
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
    return passed == len(results)


def main(argv=None):
    parser = argparse.ArgumentParser(description="replay recorded conversations through her and check what she says")
    parser.add_argument("files", nargs="*", default=sorted(str(p) for p in (HERE / "cases").glob("*.jsonl")))
    parser.add_argument("--live", metavar="URL", help="use a running llama-server instead of the scripted replies")
    parser.add_argument("-k", dest="only", help="only run cases whose name matches this regex")
    parser.add_argument("--json", dest="json_out", help="also write the results to this file")
    args = parser.parse_args(argv)
    logs.setup("WARNING")
    results = asyncio.run(run(load_cases(args.files, args.only), args.live))
    ok = report(results)
    if args.json_out:
        rows = [
            {
                "name": r.case.name,
                "passed": r.passed,
                "sent": r.sent,
                "failures": r.failures,
                "seconds": r.seconds,
                "llm_calls": r.llm_calls,
                "fallbacks": dict(r.fallbacks),
            }
            for r in results
        ]
        Path(args.json_out).write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
