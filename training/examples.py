LEAK_MARKERS = ("(notes only you can see", "You are ", "<|im_start|>", "What to tell them:")
WARNED = set()


def encode(tok, text, spans):
    try:
        enc = tok(text, add_special_tokens=False, return_offsets_mapping=True)
        ids, offsets = enc["input_ids"], enc["offset_mapping"]
        labels = [-100] * len(ids)
        for i, (a, b) in enumerate(offsets):
            if b > a and any(s <= a < e for s, e in spans):
                labels[i] = ids[i]
        return ids, labels
    except (NotImplementedError, TypeError, ValueError, KeyError):
        if "pieces" not in WARNED:
            WARNED.add("pieces")
            print(
                "WARNING: this tokenizer can't map tokens back to characters, so the text is tokenized in pieces. "
                "the token boundaries can differ from what the bot sends at inference, use a fast tokenizer if you can"
            )
    ids, labels, pos = [], [], 0
    for a, b in list(spans) + [(len(text), len(text))]:
        for piece, learn in ((text[pos:a], False), (text[a:b], True)):
            if piece:
                p = tok(piece, add_special_tokens=False)["input_ids"]
                ids += p
                labels += p if learn else [-100] * len(p)
        pos = b
    return ids, labels


def drop_oldest(messages, learn):
    system = messages[:1] if messages and messages[0]["role"] == "system" else []
    turns = messages[len(system) :]
    learn = sorted(
        int(i) for i in (learn if learn is not None else range(sum(m["role"] == "assistant" for m in turns)))
    )
    while turns:
        gone = turns.pop(0)
        if gone["role"] == "assistant":
            learn = [i - 1 for i in learn if i > 0]
        if turns and turns[0]["role"] == "user":
            break
    if not turns or not learn or turns[-1]["role"] != "assistant":
        return None, None
    return system + turns, learn


def encode_row(tok, row, fmt, max_len):
    messages, learn, cut = row["messages"], row.get("learn"), 0
    while messages is not None:
        text, spans = fmt.training_parts(messages, row.get("notes"), learn)
        if not spans:
            return None, cut
        ids, labels = encode(tok, text, spans)
        if len(ids) <= max_len:
            return {"input_ids": ids, "labels": labels}, cut
        messages, learn = drop_oldest(messages, learn)
        cut += 1
    return None, cut
