import pytest

from mitski.llm.helper import parse_json
from mitski.llm.prompt_format import Format, scrub, strip_thinking
from mitski.vision.items import gif_title, safe_url
from mitski.vision.prompts import tidy_caption, tidy_detail

TURNS = [["user", "hi"], ["assistant", "yo"], ["user", "sup"]]


@pytest.mark.parametrize(("alias", "name"), [("chatml", "qwen"), ("mistral", "v7"), ("tekken", "v7"), ("v3", "v3")])
def test_format_aliases(alias, name):
    assert Format(alias).name == name


def test_qwen_puts_notes_right_before_the_newest_message():
    prompt = Format("qwen").chat("SYS", TURNS, "NOTES")
    assert prompt.startswith("<|im_start|>system\nSYS<|im_end|>")
    assert prompt.index("NOTES") < prompt.index("sup") and prompt.index("yo") < prompt.index("NOTES")
    assert prompt.endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n")


@pytest.mark.parametrize("name", ["qwen", "v7", "v3"])
def test_every_format_ends_ready_for_her_reply(name):
    fmt = Format(name)
    prompt = fmt.chat("SYS", TURNS)
    assert "sup" in prompt
    assert not any(prompt.endswith(stop) for stop in fmt.stop)


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("<think>plan</think>hello", "hello"),
        ("leftover</think>answer", "answer"),
        ("answer<think>unfinished", "answer"),
        ("plain", "plain"),
    ],
)
def test_strip_thinking(raw, clean):
    assert strip_thinking(raw) == clean


def test_scrub_removes_template_tokens():
    assert scrub("hi<|im_end|>[INST] there</s>") == "hi there"


@pytest.mark.parametrize(
    ("text", "data"),
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": [1, 2]}\n```', {"a": [1, 2]}),
        ('<think>hmm</think>sure: {"ok": true} done', {"ok": True}),
        ("[1, 2]", None),
        ("nothing here", None),
        ('{"broken": }', None),
    ],
)
def test_parse_json(text, data):
    assert parse_json(text) == data


@pytest.mark.parametrize(
    ("url", "title"),
    [
        ("https://tenor.com/view/cat-dance-funny-gif-12345", "cat dance funny"),
        ("https://giphy.com/gifs/happy-dance-abcDEF123", "happy dance"),
        ("https://example.com/x.gif", ""),
    ],
)
def test_gif_title(url, title):
    assert gif_title(url) == title


@pytest.mark.parametrize(
    ("url", "safe"),
    [
        ("https://media.giphy.com/x.gif", True),
        ("https://cdn.discordapp.com/a.png", True),
        ("http://cdn.discordapp.com/a.png", False),
        ("https://evil.com/cdn.discordapp.com", False),
        ("https://cdn.discordapp.com.evil.com/a", False),
        ("not a url", False),
    ],
)
def test_safe_url(url, safe):
    assert safe_url(url) is safe


@pytest.mark.parametrize(
    ("raw", "caption"),
    [
        (
            'This image shows a cat on a sofa! What a cute picture. The text says "hi".',
            'a cat on a sofa. The text says "hi"',
        ),
        ("<think>look</think>A dog [blurry].", "A dog (blurry)"),
        ("Two people waving, and it's a wholesome moment.", "Two people waving"),
    ],
)
def test_tidy_caption(raw, caption):
    assert tidy_caption(raw) == caption


def test_tidy_detail_is_capped():
    assert len(tidy_detail("word " * 400)) <= 900
