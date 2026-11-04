import glob
import inspect
import json
import math
import os
import random
import re
import subprocess
import sys

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
import torch

if not torch.cuda.is_available():
    sys.exit(
        f"torch {torch.__version__} can't use your gpu"
        + (" (it's the cpu-only build)" if "+cpu" in torch.__version__ else "")
        + ". reinstall it with cuda:\n"
        "  pip uninstall -y torch torchvision torchaudio\n"
        "  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130\n"
        "(use cu126 instead if nvidia-smi shows a CUDA Version below 13.0)"
    )

from transformers import EarlyStoppingCallback, Trainer, TrainingArguments
from unsloth import FastLanguageModel

from mitski.llm.prompt_format import Format
from training.examples import LEAK_MARKERS, encode_row

BASE_MODEL = "0bserverx/Qwen3.8-27B-Heretic-Abliterated-Uncensored"
LORA_CONFIG_FALLBACK = "Qwen/Qwen3.8-27B"
TRAIN_FILE = "data/train.jsonl"
VAL_FILE = "data/val.jsonl"
PERSONA_FILE = "data/persona.yaml"
OUT_DIR = "out_mitski2"
EXPORT_ONLY = False
MAX_SEQ_LEN = 2048
LORA_RANK = 32
LORA_ALPHA = 32
LORA_DROPOUT = 0.0
EPOCHS = 3
LR = 1e-4
BATCH = 1
GRAD_ACCUM = 16
EVAL_STEPS = 20
EARLY_STOP = 3
PRECISION = "auto"
EXPORT_LORA_GGUF = True
EXPORT_MERGED = False
GGUF_QUANT = "q4_k_m"
OFFLOAD = "auto"
LLAMA_CPP = ""
SEED = 3407

FMT = Format("qwen")


def vram_gb():
    return torch.cuda.get_device_properties(0).total_memory / 1024**3


def pick_precision():
    if PRECISION in ("bf16", "4bit"):
        return PRECISION
    gb = vram_gb()
    if gb >= 60:
        return "bf16"
    print(
        f"\n{gb:.0f}GB of vram: not enough for a bf16 lora of a 27B (~56GB), training in 4-bit instead.\n"
        f"qwen3.8 loses more quality from 4-bit training than most models. it's fine for a style tune, but an\n"
        f'80GB cloud gpu with PRECISION = "bf16" gives a better result. if this runs out of memory, lower\n'
        f"LORA_RANK to 16 (prep_data's MAX_CHARS to 3000 for shorter examples).\n"
    )
    return "4bit"


def check_tokens(tok):
    for tag in ("<|im_start|>", "<|im_end|>", "<think>", "</think>"):
        ids = tok.encode(tag, add_special_tokens=False)
        print(f"{tag} -> {ids}" + ("" if len(ids) == 1 else "  <-- WARNING: not a single token"))
        if len(ids) != 1 and "im_" in tag:
            sys.exit("the tokenizer doesn't know qwen's chat tokens, is BASE_MODEL right?")


def load_rows(tok, path):
    rows, skipped, shortened = [], 0, 0
    if not os.path.exists(path):
        return rows, skipped, shortened
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            encoded, cut = encode_row(tok, json.loads(line), FMT, MAX_SEQ_LEN)
            if encoded is None:
                skipped += 1
                continue
            shortened += bool(cut)
            rows.append(encoded)
    return rows, skipped, shortened


class Collate:
    def __init__(self, pad_id):
        self.pad_id = pad_id

    def __call__(self, batch):
        n = max(len(b["input_ids"]) for b in batch)
        ids = [b["input_ids"] + [self.pad_id] * (n - len(b["input_ids"])) for b in batch]
        labels = [b["labels"] + [-100] * (n - len(b["labels"])) for b in batch]
        mask = [[1] * len(b["input_ids"]) + [0] * (n - len(b["input_ids"])) for b in batch]
        return {"input_ids": torch.tensor(ids), "labels": torch.tensor(labels), "attention_mask": torch.tensor(mask)}


def check_masking(tok, rows):
    for n, r in enumerate(rows):
        learned = [t for t, label in zip(r["input_ids"], r["labels"], strict=True) if label != -100]
        if not learned:
            sys.exit(f"nothing to learn in example {n}: the masking doesn't match the text")
        text = tok.decode(learned)
        if any(marker in text for marker in LEAK_MARKERS):
            sys.exit(f"example {n} lets her learn the system prompt or notes:\n{text[:300]!r}")
    row = rows[0]
    learn = [t for t in row["labels"] if t != -100]
    total = sum(sum(1 for t in r["labels"] if t != -100) for r in rows)
    print(
        f"masking: she learns {total} tokens over {len(rows)} examples "
        f"({total / max(1, sum(len(r['labels']) for r in rows)):.0%} of what she reads). first example learns:\n"
        + repr(tok.decode(learn)[:400])
        + "\n"
    )


def training_args(n_train, has_val):
    steps = math.ceil(n_train / (BATCH * GRAD_ACCUM)) * EPOCHS
    args = dict(
        output_dir=os.path.join(OUT_DIR, "checkpoints"),
        per_device_train_batch_size=BATCH,
        per_device_eval_batch_size=BATCH,
        gradient_accumulation_steps=GRAD_ACCUM,
        num_train_epochs=EPOCHS,
        learning_rate=LR,
        lr_scheduler_type="cosine",
        warmup_steps=max(1, round(steps * 0.05)),
        weight_decay=0.01,
        max_grad_norm=1.0,
        optim="adamw_8bit",
        logging_steps=5,
        eval_strategy="steps" if has_val else "no",
        eval_steps=EVAL_STEPS,
        save_strategy="steps",
        save_steps=EVAL_STEPS,
        save_total_limit=3,
        load_best_model_at_end=has_val,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        remove_unused_columns=False,
        dataloader_num_workers=0,
        seed=SEED,
        report_to="none",
        bf16=torch.cuda.is_bf16_supported(),
        fp16=not torch.cuda.is_bf16_supported(),
    )
    params = inspect.signature(TrainingArguments.__init__).parameters
    if "eval_strategy" not in params and "evaluation_strategy" in params:
        args["evaluation_strategy"] = args.pop("eval_strategy")
    dropped = [k for k in args if k not in params]
    for k in dropped:
        args.pop(k)
    if dropped:
        print(f"(this transformers doesn't take {dropped}, going without)")
    return TrainingArguments(**args), steps


def find_llama_cpp():
    for d in [
        LLAMA_CPP,
        "llama.cpp",
        os.path.join(os.path.expanduser("~"), "llama.cpp"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "llama.cpp"),
    ]:
        if d and os.path.exists(os.path.join(d, "convert_lora_to_gguf.py")):
            return d
    return None


def export_lora_gguf(lora_dir):
    out = os.path.join(OUT_DIR, "mitski-lora-f16.gguf")
    llama = find_llama_cpp()
    cmd_hint = (
        f"python llama.cpp/convert_lora_to_gguf.py {lora_dir} --outfile {out} --outtype f16 "
        f"--base-model-id {BASE_MODEL}"
    )
    if llama is None:
        print(
            "\nno llama.cpp checkout found for the lora conversion. get one and run:\n"
            "  git clone --depth 1 https://github.com/ggml-org/llama.cpp\n"
            "  pip install --no-deps -e llama.cpp/gguf-py\n"
            "(not the requirements file: it installs the cpu-only torch over your cuda one)\n"
            f"  {cmd_hint}\n"
        )
        return None
    for base in dict.fromkeys([BASE_MODEL, LORA_CONFIG_FALLBACK]):
        cmd = [
            sys.executable,
            os.path.join(llama, "convert_lora_to_gguf.py"),
            lora_dir,
            "--outfile",
            out,
            "--outtype",
            "f16",
            "--base-model-id",
            base,
        ]
        print("converting the lora for llama-server: " + " ".join(cmd))
        try:
            subprocess.run(cmd, check=True)
        except (subprocess.CalledProcessError, OSError) as e:
            print(f"lora conversion with {base}'s config failed ({e})")
            continue
        print(f"saved lora gguf -> {out}")
        return out
    print(
        f"lora conversion failed. update llama.cpp (git pull) and try:\n  {cmd_hint}\n"
        f"if it still fails, set EXPORT_ONLY = True and EXPORT_MERGED = True to make a merged gguf from the lora "
        f"you already trained (then LORA_SCALE: 0 in the bot)"
    )
    return None


def read_persona():
    out = {}
    if os.path.exists(PERSONA_FILE):
        try:
            import yaml

            with open(PERSONA_FILE, encoding="utf-8") as f:
                out = yaml.safe_load(f) or {}
        except Exception as e:
            print(f"couldn't read {PERSONA_FILE}: {e}")
    return out


def vibe_check(model, tok, persona, style_note):
    FastLanguageModel.for_inference(model)
    notes = (
        "(notes only you can see, for your next message)\nIt's Saturday in the evening (21:14).\n"
        "You're chatting in #game-chat with skye, jay.\n"
        + (style_note + "\n" if style_note else "")
        + "Use these notes only where they fit, the way a real person would, and never mention them."
    )
    for turns in (
        [["user", "heyy whats up"]],
        [["user", "skye: did u see what happened in vc last night\njay: LMAO"]],
        [
            ["user", "jay: ur so bad at this game lol"],
            ["assistant", "says the guy who died first"],
            ["user", "jay: that was lag i swear"],
        ],
        [["user", "skye: what games are u playing rn"]],
    ):
        text = FMT.chat(persona, turns, notes)
        ids = tok(text, return_tensors="pt", add_special_tokens=False).to("cuda")
        out = model.generate(
            **ids,
            max_new_tokens=80,
            do_sample=True,
            temperature=0.8,
            top_p=0.8,
            top_k=20,
            eos_token_id=tok.convert_tokens_to_ids("<|im_end|>"),
        )
        reply = tok.decode(out[0][ids["input_ids"].shape[1] :], skip_special_tokens=True)
        print(f"> {turns[-1][1]}\n{reply.strip()}\n")


def load_model(precision, name=None):
    kwargs = dict(
        model_name=name or BASE_MODEL,
        max_seq_length=MAX_SEQ_LEN,
        load_in_4bit=precision == "4bit",
        load_in_16bit=precision == "bf16",
        full_finetuning=False,
    )
    try:
        return FastLanguageModel.from_pretrained(**kwargs)
    except ValueError as e:
        if OFFLOAD == "off" or not re.search(r"does not fit in GPU memory|dispatched on the CPU", str(e)):
            raise
    free = torch.cuda.mem_get_info()[0] / 1024**3
    print(
        f"\nthe model doesn't fit in the {free:.1f}GB of free vram, so the layers that don't fit go to system ram and\n"
        f"get streamed in while training. that's slower (expect a few times longer per step), but it works.\n"
        f"closing anything else on the gpu (llama-server, ollama, games, browser tabs) leaves more of it on the gpu.\n"
    )
    torch.cuda.empty_cache()
    return FastLanguageModel.from_pretrained(**kwargs, offload_layers="auto")


def export_only():
    lora_dir = os.path.join(OUT_DIR, "lora")
    if not os.path.exists(os.path.join(lora_dir, "adapter_config.json")):
        sys.exit(f"EXPORT_ONLY is on but there's no trained lora in {lora_dir}")
    if EXPORT_LORA_GGUF:
        export_lora_gguf(lora_dir)
    if EXPORT_MERGED:
        model, tokenizer = load_model(pick_precision(), lora_dir)
        gguf_dir = os.path.join(OUT_DIR, "gguf")
        model.save_pretrained_gguf(gguf_dir, tokenizer, quantization_method=GGUF_QUANT)
        print(f"saved merged gguf ({GGUF_QUANT}) -> {gguf_dir}")


def main():
    if EXPORT_ONLY:
        return export_only()
    random.seed(SEED)
    precision = pick_precision()
    print(f"loading {BASE_MODEL} for a {precision} lora")
    model, tokenizer = load_model(precision)
    tok = getattr(tokenizer, "tokenizer", tokenizer)
    tok.model_max_length = MAX_SEQ_LEN
    if tok.pad_token is None:
        tok.pad_token = "<|endoftext|>"
    check_tokens(tok)

    train, too_long, cut = load_rows(tok, TRAIN_FILE)
    val, too_long_val, cut_val = load_rows(tok, VAL_FILE)
    if not train:
        sys.exit(f"no training examples in {TRAIN_FILE}, run prep_data.py first")
    if cut or cut_val:
        print(f"shortened {cut + cut_val} examples longer than MAX_SEQ_LEN ({MAX_SEQ_LEN} tokens) by dropping old chat")
    if too_long or too_long_val:
        print(
            f"skipped {too_long + too_long_val} examples that were still too long. if that's a lot, raise "
            f"MAX_SEQ_LEN or lower MAX_CHARS in prep_data.py"
        )
    lengths = sorted(len(r["input_ids"]) for r in train)
    print(
        f"{len(train)} train / {len(val)} val examples, {lengths[len(lengths) // 2]} tokens typical, "
        f"{lengths[-1]} longest"
    )
    check_masking(tok, train)

    model = FastLanguageModel.get_peft_model(
        model,
        r=LORA_RANK,
        lora_alpha=LORA_ALPHA,
        lora_dropout=LORA_DROPOUT,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth",
        random_state=SEED,
    )
    args, steps = training_args(len(train), bool(val))
    callbacks = [EarlyStoppingCallback(early_stopping_patience=EARLY_STOP)] if val and EARLY_STOP > 0 else []
    print(
        f"up to {steps} optimizer steps ({EPOCHS} epochs), val loss every {EVAL_STEPS}"
        if val
        else f"{steps} optimizer steps, no val set (so no best-checkpoint pick or early stop)"
    )
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=train,
        eval_dataset=val or None,
        data_collator=Collate(tok.pad_token_id),
        callbacks=callbacks,
    )
    trainer.train()
    if val:
        best = trainer.state.best_metric
        print(
            f"best val loss: {best:.4f}"
            + (f" ({trainer.state.best_model_checkpoint})" if trainer.state.best_model_checkpoint else "")
        )

    persona = read_persona()
    lora_dir = os.path.join(OUT_DIR, "lora")
    model.save_pretrained(lora_dir)
    tokenizer.save_pretrained(lora_dir)
    with open(os.path.join(lora_dir, "mitski_persona.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "PERSONA": persona.get("PERSONA", ""),
                "STYLE_NOTE": persona.get("STYLE_NOTE", ""),
                "PROMPT_FORMAT": "qwen",
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"saved lora adapter -> {lora_dir}")

    if persona.get("PERSONA"):
        vibe_check(model, tok, persona["PERSONA"], persona.get("STYLE_NOTE", ""))

    if EXPORT_LORA_GGUF:
        export_lora_gguf(lora_dir)

    if EXPORT_MERGED:
        gguf_dir = os.path.join(OUT_DIR, "gguf")
        try:
            model.save_pretrained_gguf(gguf_dir, tokenizer, quantization_method=GGUF_QUANT)
            made = glob.glob(gguf_dir + "*/**/*.gguf", recursive=True) + glob.glob(gguf_dir + "*/*.gguf")
            print(f"saved merged gguf ({GGUF_QUANT}) -> " + (", ".join(sorted(set(made))) or gguf_dir))
        except Exception as e:
            print(f"merged gguf export failed: {e}")
            merged_dir = os.path.join(OUT_DIR, "merged")
            model.save_pretrained_merged(merged_dir, tokenizer, save_method="merged_16bit")
            print(
                f"saved full merged model -> {merged_dir} (convert it to gguf with llama.cpp's convert_hf_to_gguf.py)"
            )

    print(
        f"\nnext: put PERSONA and STYLE_NOTE from {PERSONA_FILE} in config/mitski.yaml (the exact same text), and point "
        f"llama-server's --lora at {os.path.join(OUT_DIR, 'mitski-lora-f16.gguf')}"
    )
    if "heretic" in BASE_MODEL.lower():
        print(
            "the heretic gguf her lora goes on, if you don't have it yet (your mmproj-F16.gguf still works for her eyes):\n"
            "  hf download 0bserverx/Qwen3.8-27B-Heretic-Abliterated-Uncensored-GGUF RVN-Q4_K_M-multilingual.gguf "
            "--local-dir models"
        )
    else:
        print(
            "the plain model + its vision projector for llama-server:\n"
            "  hf download unsloth/Qwen3.8-27B-GGUF Qwen3.8-27B-UD-Q4_K_XL.gguf mmproj-F16.gguf --local-dir models"
        )


if __name__ == "__main__":
    main()
