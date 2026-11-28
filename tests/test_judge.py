import io
import json

from aiohttp import web

from evals.judge import DIMENSIONS, Judge, read_scores, rubric_text, schema, wanted
from evals.replay import Case, compare, her_settings, report, rows_of, run


class FakeJudge(Judge):
    def __init__(self, score=4, runs=1):
        super().__init__(None, runs=runs)
        self.asked = []
        self.score_of = score

    async def ask(self, world, system, user, schema_):
        self.asked.append(user)
        n = self.score_of(len(self.asked)) if callable(self.score_of) else self.score_of
        return {d: {"why": f"{d} because", "score": n} for d in schema_["properties"]}


def case(**more):
    raw = {
        "name": "hi",
        "turns": [{"from": "anna", "text": "mitski where r u from"}],
        "replies": ["portugal hbu"],
        "expect": {"reply": True},
        **more,
    }
    return Case.from_json(raw)


async def test_her_replies_are_graded_on_every_dimension():
    judge = FakeJudge(4)
    [r] = await run([case(rubric={"in_character": "portugal or a 1"})], live=None, judge=judge)
    assert set(r.scores) == set(DIMENSIONS) and r.persona_score == 4
    prompt = judge.asked[0]
    assert "anna: mitski where r u from" in prompt and "mitski: portugal hbu" in prompt
    assert "For this chat: portugal or a 1" in prompt and "never a fault" in prompt


async def test_a_case_can_pick_what_is_graded_or_skip_it():
    [some] = await run([case(judge=["voice", "fits"])], live=None, judge=FakeJudge())
    [none] = await run([case(judge=False)], live=None, judge=FakeJudge())
    assert set(some.scores) == {"voice", "fits"} and none.scores == {}


async def test_silence_is_not_graded():
    judge = FakeJudge()
    [r] = await run([case(replies=[""] * 3, expect={})], live=None, judge=judge)
    assert r.sent == [] and r.scores == {} and judge.asked == []


async def test_a_score_below_the_minimum_fails_the_case():
    [r] = await run([case(expect={"reply": True, "min_scores": {"voice": 4}})], live=None, judge=FakeJudge(2))
    assert not r.passed and "voice scored 2.0, wants 4" in r.failures


async def test_several_runs_are_averaged():
    [r] = await run([case()], live=None, judge=FakeJudge(lambda n: 3 if n == 1 else 5, runs=2))
    assert r.scores["voice"][0] == 4 and len(r.scores["voice"][1]) == 2


def test_the_report_shows_scores_and_why_low_ones_are_low():
    from evals.replay import Result

    r = Result(case(), ["hi"], [], 0.1, 1, scores={"voice": (2.0, ["sounds like an assistant"]), "fits": (5.0, [])})
    out = io.StringIO()
    report([r], out)
    text = out.getvalue()
    assert "voice 2.0 · fits 5.0 = 3.50" in text and "voice: sounds like an assistant" in text
    assert "persona score 3.50 over 1 cases" in text


def test_compare_shows_what_changed():
    new = [
        {"name": "a", "passed": True, "llm_calls": 1, "fallbacks": {}, "scores": {"voice": 5, "fits": 5}},
        {"name": "b", "passed": False, "llm_calls": 3, "fallbacks": {"redo robotic": 1}, "scores": {"voice": 2}},
    ]
    old = [
        {
            "name": "a",
            "passed": False,
            "llm_calls": 2,
            "fallbacks": {"redo echo": 1},
            "scores": {"voice": 3, "fits": 3},
        },
        {"name": "b", "passed": False, "llm_calls": 3, "fallbacks": {}},
    ]
    out = io.StringIO()
    compare(old, new, out)
    text = out.getvalue()
    assert "passed 0 -> 1" in text and "now passes: a" in text and "better (3.00 -> 5.00): a" in text
    assert "voice 3.00 -> 3.50" in text


def test_scores_are_clamped_and_bad_ones_skipped():
    got = read_scores({"voice": {"why": "x", "score": 9}, "fits": {"score": "?"}, "human": "nope"}, DIMENSIONS)
    assert got == {"voice": (5, "x")}


def test_schema_and_rubric_cover_what_is_asked():
    dims = wanted(["fits", "nonsense", "voice"])
    assert dims == ("voice", "fits")
    assert set(schema(dims)["required"]) == {"voice", "fits"}
    text = rubric_text(dims, {"fits": "answer bob"})
    assert text.count("  1 = ") == 2 and "For this chat: answer bob" in text and "human:" not in text
    assert wanted(None) == DIMENSIONS and wanted(False) == ()


def test_live_runs_use_who_she_is_but_keep_the_test_world_quiet(tmp_path):
    path = tmp_path / "mitski.yaml"
    path.write_text(
        "PERSONA: you're mitski\nHER_AGE: 20\nTEMPERATURE: 0.9\nCHANNELS: [1]\nREAD_DELAY: [5, 9]\nVISION: true\n",
        encoding="utf-8",
    )
    assert her_settings(path) == {"PERSONA": "you're mitski", "HER_AGE": 20, "TEMPERATURE": 0.9}
    assert her_settings(tmp_path / "missing.yaml") == {}


async def test_an_outside_judge_gets_the_rubric_as_json_schema():
    seen = []

    async def completions(request):
        body = await request.json()
        seen.append((body, request.headers.get("Authorization")))
        props = body["response_format"]["json_schema"]["schema"]["properties"]
        grades = {d: {"why": "ok", "score": 3} for d in props}
        return web.json_response({"choices": [{"message": {"content": "```json\n" + json.dumps(grades) + "\n```"}}]})

    app = web.Application()
    app.router.add_post("/v1/chat/completions", completions)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        judge = Judge(f"http://127.0.0.1:{port}", model="judge-model", key="secret")
        [r] = await run([case()], live=None, judge=judge)
    finally:
        await runner.cleanup()
    body, auth = seen[0]
    assert auth == "Bearer secret" and body["model"] == "judge-model" and body["temperature"] == 0.0
    assert r.scores["fits"][0] == 3
    assert rows_of([r])[0]["scores"]["fits"] == 3
