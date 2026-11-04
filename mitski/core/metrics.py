import contextvars
import statistics
import time
from collections import Counter, deque
from contextlib import contextmanager
from dataclasses import dataclass, field

_current = contextvars.ContextVar("mitski_trace", default=None)


@dataclass
class Trace:
    mode: str
    started: float = field(default_factory=time.monotonic)
    calls: Counter = field(default_factory=Counter)
    llm_seconds: float = 0.0
    stages: dict = field(default_factory=dict)
    first_send: float | None = None
    outcome: str = "dropped"
    events: Counter = field(default_factory=Counter)

    @property
    def total_calls(self):
        return sum(self.calls.values())

    @property
    def to_first_send(self):
        return None if self.first_send is None else self.first_send - self.started

    def summary(self):
        calls = ", ".join(f"{k} {v}" for k, v in sorted(self.calls.items())) or "none"
        sent = f"{self.to_first_send:.1f}s to first message" if self.to_first_send is not None else "nothing sent"
        events = f" | {', '.join(f'{k} {v}' for k, v in sorted(self.events.items()))}" if self.events else ""
        return f"{self.outcome}: {sent}, {self.total_calls} llm calls ({calls}), {self.llm_seconds:.1f}s on the llm{events}"


class Metrics:
    def __init__(self, window=200):
        self.done = deque(maxlen=window)
        self.totals = Counter()

    @contextmanager
    def trace(self, mode):
        trace = Trace(mode)
        token = _current.set(trace)
        try:
            yield trace
        finally:
            _current.reset(token)
            self.done.append(trace)

    @staticmethod
    def current():
        return _current.get()

    @staticmethod
    def llm_call(kind, seconds):
        trace = _current.get()
        if trace is not None:
            trace.calls[kind] += 1
            trace.llm_seconds += seconds

    @staticmethod
    def event(name):
        trace = _current.get()
        if trace is not None:
            trace.events[name] += 1

    def count(self, name):
        self.totals[name] += 1

    @staticmethod
    @contextmanager
    def stage(name):
        trace = _current.get()
        start = time.monotonic()
        try:
            yield
        finally:
            if trace is not None:
                trace.stages[name] = trace.stages.get(name, 0.0) + time.monotonic() - start

    @staticmethod
    def sent():
        trace = _current.get()
        if trace is not None and trace.first_send is None:
            trace.first_send = time.monotonic()
            trace.outcome = "sent"

    def report(self):
        replies = [t for t in self.done if t.to_first_send is not None]
        if not replies:
            return "no replies measured yet"
        latency = sorted(t.to_first_send for t in replies)
        calls = sorted(t.total_calls for t in replies)
        stages = Counter()
        for t in replies:
            stages.update(t.stages)
        by_mode = Counter(t.mode for t in replies)
        events = Counter()
        for t in self.done:
            events.update(t.events)
        lines = [
            f"**{len(replies)} replies** ({', '.join(f'{m} {n}' for m, n in by_mode.most_common())}), "
            f"{len(self.done) - len(replies)} dropped",
            f"time to first message: p50 {_pct(latency, 50):.1f}s · p95 {_pct(latency, 95):.1f}s · "
            f"max {latency[-1]:.1f}s",
            f"llm calls per reply: p50 {_pct(calls, 50):.0f} · p95 {_pct(calls, 95):.0f} · "
            f"mean {statistics.fmean(calls):.1f}",
            "avg per stage: "
            + " · ".join(f"{k} {v / len(replies):.1f}s" for k, v in sorted(stages.items(), key=lambda kv: -kv[1])),
        ]
        if events:
            lines.append(
                "fallbacks per 100 replies: "
                + " · ".join(f"{k} {100 * v / len(self.done):.0f}" for k, v in events.most_common())
            )
        if self.totals:
            lines.append("since start: " + " · ".join(f"{k} {v}" for k, v in self.totals.most_common()))
        return "\n".join(lines)


def _pct(values, p):
    if not values:
        return 0.0
    k = (len(values) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)
