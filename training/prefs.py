import json
import os

import torch
import torch.nn.functional as F

from training.examples import encode_row


def load_pairs(path, sources=("her",), kinds=None):
    if not os.path.exists(path):
        return []
    pairs, seen = [], set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                p = json.loads(line)
            except json.JSONDecodeError:
                continue
            if sources and p.get("source", "her") not in sources:
                continue
            if kinds and p.get("kind") not in kinds:
                continue
            turns = p.get("turns") or []
            if not turns or turns[-1][0] != "user" or not p.get("chosen") or not p.get("rejected"):
                continue
            key = (p["chosen"], p["rejected"])
            if key in seen:
                continue
            seen.add(key)
            pairs.append(p)
    return pairs


def split(pairs, share, rng):
    pairs = list(pairs)
    rng.shuffle(pairs)
    n = round(len(pairs) * share) if len(pairs) >= 20 else 0
    return pairs[n:], pairs[:n]


def as_rows(pair):
    messages = [{"role": "system", "content": pair.get("system") or ""}]
    messages += [{"role": role, "content": text} for role, text in pair["turns"]]
    hers = sum(1 for role, _ in pair["turns"] if role == "assistant")

    def row(reply):
        return {
            "messages": [*messages, {"role": "assistant", "content": reply}],
            "notes": pair.get("notes"),
            "learn": [hers],
        }

    return row(pair["chosen"]), row(pair["rejected"])


def encode_pair(tok, pair, fmt, max_len):
    chosen_row, rejected_row = as_rows(pair)
    chosen, _ = encode_row(tok, chosen_row, fmt, max_len)
    rejected, _ = encode_row(tok, rejected_row, fmt, max_len)
    if chosen is None or rejected is None:
        return None
    if not any(x != -100 for x in chosen["labels"]) or not any(x != -100 for x in rejected["labels"]):
        return None
    return {"chosen": chosen, "rejected": rejected}


class PairCollate:
    def __init__(self, pad_id):
        self.pad_id = pad_id

    def __call__(self, batch):
        seqs = [b["chosen"] for b in batch] + [b["rejected"] for b in batch]
        n = max(len(s["input_ids"]) for s in seqs)
        ids = [s["input_ids"] + [self.pad_id] * (n - len(s["input_ids"])) for s in seqs]
        labels = [s["labels"] + [-100] * (n - len(s["labels"])) for s in seqs]
        mask = [[1] * len(s["input_ids"]) + [0] * (n - len(s["input_ids"])) for s in seqs]
        return {
            "input_ids": torch.tensor(ids),
            "labels": torch.tensor(labels),
            "attention_mask": torch.tensor(mask),
            "n_pairs": len(batch),
        }


def seq_logps(logits, labels):
    logits = logits[:, :-1].float()
    labels = labels[:, 1:]
    mask = labels != -100
    picked = torch.gather(torch.log_softmax(logits, -1), 2, labels.clamp(min=0).unsqueeze(-1)).squeeze(-1)
    total = (picked * mask).sum(-1)
    count = mask.sum(-1).clamp(min=1)
    return total / count


def pair_loss(avg, n, beta, gamma, alpha):
    chosen, rejected = avg[:n], avg[n:]
    margin = beta * (chosen - rejected) - gamma
    return -F.logsigmoid(margin).mean() - alpha * chosen.mean(), (chosen > rejected).float().mean()


def batch_loss(model, inputs, beta, gamma, alpha):
    out = model(input_ids=inputs["input_ids"], attention_mask=inputs["attention_mask"])
    loss, _ = pair_loss(seq_logps(out.logits, inputs["labels"]), int(inputs["n_pairs"]), beta, gamma, alpha)
    return loss, out


@torch.no_grad()
def accuracy(model, pairs, collate, device="cuda"):
    if not pairs:
        return None, None
    was_training = model.training
    model.eval()
    right, margins = 0, []
    for p in pairs:
        batch = collate([p])
        out = model(input_ids=batch["input_ids"].to(device), attention_mask=batch["attention_mask"].to(device))
        avg = seq_logps(out.logits, batch["labels"].to(device))
        right += int(avg[0] > avg[1])
        margins.append(float(avg[0] - avg[1]))
    if was_training:
        model.train()
    return right / len(pairs), sum(margins) / len(margins)
