import pytest

from mitski.llm.prompt_format import Format
from training.examples import drop_oldest, encode, encode_row
from training.prep_data import brief_of


class CharTokenizer:
    def __call__(self, text, add_special_tokens=False, return_offsets_mapping=False):
        out = {"input_ids": [ord(c) for c in text]}
        if return_offsets_mapping:
            out["offset_mapping"] = [(i, i + 1) for i in range(len(text))]
        return out

    def decode(self, ids):
        return "".join(map(chr, ids))


def conversation(n):
    msgs = [{"role": "system", "content": "SYS"}]
    for i in range(n):
        msgs += [{"role": "user", "content": f"q{i}"}, {"role": "assistant", "content": f"a{i}"}]
    return msgs


def learned(tok, row):
    return tok.decode([t for t, label in zip(row["input_ids"], row["labels"], strict=True) if label != -100])


def test_only_her_replies_are_learned():
    tok, fmt = CharTokenizer(), Format("qwen")
    text, spans = fmt.training_parts(conversation(2), "NOTES", [1])
    ids, labels = encode(tok, text, spans)
    assert tok.decode([t for t, label in zip(ids, labels, strict=True) if label != -100]) == "a1<|im_end|>"


def test_inference_prompt_is_a_prefix_of_the_training_text():
    fmt = Format("qwen")
    text, _ = fmt.training_parts(conversation(2), "NOTES", [1])
    prompt = fmt.chat("SYS", [["user", "q0"], ["assistant", "a0"], ["user", "q1"]], "NOTES")
    assert text.startswith(prompt)


@pytest.mark.parametrize(("n", "learn", "kept_learn"), [(3, [2], [1]), (3, [0, 2], [1]), (1, [0], None)])
def test_drop_oldest_keeps_the_learned_replies_aligned(n, learn, kept_learn):
    messages, new_learn = drop_oldest(conversation(n), learn)
    assert new_learn == kept_learn
    if messages is not None:
        assert messages[0]["role"] == "system" and messages[1]["role"] == "user"


def test_long_examples_are_shortened_not_dropped():
    tok, fmt = CharTokenizer(), Format("qwen")
    row = {"messages": conversation(6), "notes": None, "learn": [5]}
    full, _ = encode_row(tok, row, fmt, 10_000)
    short, cut = encode_row(tok, row, fmt, len(full["input_ids"]) - 1)
    assert cut >= 1
    assert learned(tok, short) == "a5<|im_end|>"
    assert len(short["input_ids"]) < len(full["input_ids"])


def test_examples_that_never_fit_are_skipped():
    tok, fmt = CharTokenizer(), Format("qwen")
    encoded, _ = encode_row(tok, {"messages": conversation(2), "learn": [1]}, fmt, 5)
    assert encoded is None


@pytest.mark.parametrize(
    ("said", "reply", "brief"),
    [
        ("whats the capital of australia?", "its canberra lmao", "canberra"),
        ("hi", "hii", None),
        ("what time?", "what time u want?", None),
        ("which game?", "valorant or cs2 idk", "valorant or cs2"),
        ("why?", "because it was really late and i was tired and bored and hungry", None),
    ],
)
def test_brief_of(said, reply, brief):
    assert brief_of(said, reply) == brief
