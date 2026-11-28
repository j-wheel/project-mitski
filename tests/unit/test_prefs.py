import json
import random
from types import SimpleNamespace

import pytest

torch = pytest.importorskip("torch")

from mitski.llm.prompt_format import Format  # noqa: E402
from training.prefs import (  # noqa: E402
    PairCollate,
    accuracy,
    batch_loss,
    encode_pair,
    load_pairs,
    pair_loss,
    seq_logps,
    split,
)


class CharTokenizer:
    pad_token_id = 0

    def __call__(self, text, add_special_tokens=False, return_offsets_mapping=False):
        out = {"input_ids": [ord(c) % 256 for c in text]}
        if return_offsets_mapping:
            out["offset_mapping"] = [(i, i + 1) for i in range(len(text))]
        return out

    def decode(self, ids):
        return "".join(map(chr, ids))


class Tiny(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.emb = torch.nn.Embedding(256, 16)
        self.out = torch.nn.Linear(16, 256)

    def forward(self, input_ids, attention_mask=None, **_):
        return SimpleNamespace(logits=self.out(self.emb(input_ids)))


def pair(chosen="ya im here", rejected="she is here", **more):
    return {
        "kind": "third person",
        "source": "her",
        "system": "SYS",
        "turns": [["user", "u there"], ["assistant", "hii"], ["user", "anna: are u still here"]],
        "notes": "NOTES",
        "chosen": chosen,
        "rejected": rejected,
        **more,
    }


def write(tmp_path, rows):
    path = tmp_path / "preferences.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n", encoding="utf-8")
    return str(path)


def test_pairs_are_filtered_and_deduped(tmp_path):
    path = write(
        tmp_path,
        [
            pair(),
            pair(),
            pair(chosen="hm", source="plain"),
            pair(chosen="yo", kind="not safe"),
            {**pair(chosen="late"), "turns": [["user", "x"], ["assistant", "y"]]},
        ],
    )
    assert [p["chosen"] for p in load_pairs(path)] == ["ya im here", "yo"]
    assert [p["chosen"] for p in load_pairs(path, sources=None)] == ["ya im here", "hm", "yo"]
    assert [p["chosen"] for p in load_pairs(path, kinds={"not safe"})] == ["yo"]
    assert load_pairs(str(tmp_path / "missing.jsonl")) == []


def test_only_the_final_reply_is_learned():
    tok = CharTokenizer()
    enc = encode_pair(tok, pair(), Format("qwen"), 10_000)
    for side, reply in (("chosen", "ya im here"), ("rejected", "she is here")):
        row = enc[side]
        learned = tok.decode([t for t, label in zip(row["input_ids"], row["labels"], strict=True) if label != -100])
        assert learned == reply + "<|im_end|>"
    prompt = Format("qwen").chat("SYS", pair()["turns"], "NOTES")
    assert tok.decode(enc["chosen"]["input_ids"]).startswith(prompt)


def test_pairs_too_long_to_fit_are_dropped():
    assert encode_pair(CharTokenizer(), pair(), Format("qwen"), 20) is None


def test_collate_puts_chosen_before_rejected():
    tok = CharTokenizer()
    encoded = [
        encode_pair(tok, pair(), Format("qwen"), 10_000),
        encode_pair(tok, pair(chosen="k"), Format("qwen"), 10_000),
    ]
    batch = PairCollate(0)(encoded)
    assert batch["n_pairs"] == 2 and batch["input_ids"].shape[0] == 4
    assert batch["input_ids"].shape == batch["labels"].shape == batch["attention_mask"].shape
    assert int(batch["attention_mask"][0].sum()) == len(encoded[0]["chosen"]["input_ids"])
    assert int(batch["attention_mask"][2].sum()) == len(encoded[0]["rejected"]["input_ids"])


def test_seq_logps_averages_only_the_learned_tokens():
    logits = torch.zeros(1, 4, 3)
    logits[0, 1, 2] = 10.0
    labels = torch.tensor([[-100, -100, 2, -100]])
    expected = torch.log_softmax(logits[0, 1], -1)[2]
    assert torch.allclose(seq_logps(logits, labels), expected.unsqueeze(0))


def test_the_loss_wants_a_margin():
    good = pair_loss(torch.tensor([-1.0, -3.0]), 1, 2.0, 1.0, 0.0)
    bad = pair_loss(torch.tensor([-3.0, -1.0]), 1, 2.0, 1.0, 0.0)
    assert good[0] < bad[0] and good[1] == 1 and bad[1] == 0


def test_training_on_pairs_makes_her_prefer_the_redo():
    torch.manual_seed(0)
    tok, fmt = CharTokenizer(), Format("qwen")
    rng = random.Random(0)
    raw = [pair(chosen=f"ya im here {i}", rejected=f"she is here {i}") for i in range(30)]
    encoded = [encode_pair(tok, p, fmt, 10_000) for p in raw]
    train, held = split(encoded, 0.2, rng)
    assert len(held) == 6 and len(train) == 24
    model, collate = Tiny(), PairCollate(0)
    opt = torch.optim.AdamW(model.parameters(), lr=5e-2)
    _, before_margin = accuracy(model, held, collate, device="cpu")
    for _ in range(4):
        for i in range(0, len(train), 2):
            loss, _ = batch_loss(model, collate(train[i : i + 2]), 2.0, 1.0, 0.2)
            opt.zero_grad()
            loss.backward()
            opt.step()
    after, margin = accuracy(model, held, collate, device="cpu")
    assert model.training
    assert after == 1.0 and margin > before_margin and margin > 0


def test_few_pairs_are_all_used_for_training():
    train, held = split(list(range(10)), 0.1, random.Random(0))
    assert held == [] and sorted(train) == list(range(10))
