import pytest

from evals.replay import HERE, check, load_cases, run


async def test_scripted_cases_pass():
    results = await run(load_cases(sorted((HERE / "cases").glob("*.jsonl"))), live=None)
    failed = [(r.case.name, r.failures) for r in results if not r.passed]
    assert results and not failed, failed


@pytest.mark.parametrize(
    ("expect", "sent", "problems"),
    [
        ({"reply": True}, [], 1),
        ({"silent": True}, ["hi"], 1),
        ({"contains": ["Hi"], "not_contains": ["assist"]}, ["hi there"], 0),
        ({"matches": [r"\bu\?$"]}, ["and u?"], 0),
        ({"max_messages": 1}, ["a", "b"], 1),
    ],
)
def test_check(expect, sent, problems):
    assert len(check(expect, sent)) == problems
