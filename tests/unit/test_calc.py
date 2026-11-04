import pytest

from mitski.brain.calc import calc


@pytest.mark.parametrize(
    ("expr", "answer"),
    [
        ("2+2", "4"),
        ("2^10", "1024"),
        ("15% of 200", "30"),
        ("sqrt(16)", "4"),
        ("1,000*3", "3000"),
        ("2x3", "6"),
    ],
)
def test_solves(expr, answer):
    assert calc(expr).endswith(f"= {answer}")


@pytest.mark.parametrize("expr", ['__import__("os")', "10/0", "9**999", "", "hello there", "x" * 200])
def test_refuses(expr):
    assert calc(expr) is None
