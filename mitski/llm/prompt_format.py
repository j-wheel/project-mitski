import re

SPECIAL = re.compile(
    r"<\|[A-Za-z0-9_]{1,40}\|>|</?think>|\[/?(?:INST|SYSTEM_PROMPT|AVAILABLE_TOOLS|TOOL_RESULTS|"
    r"TOOL_CALLS)\]|</?s>"
)
THINK = re.compile(r"<think>.*?</think>\s*", re.S | re.I)

QWEN_SYS = "<|im_start|>system\n{}<|im_end|>\n"
QWEN_USER = "<|im_start|>user\n{}<|im_end|>\n"
QWEN_REPLY = "<|im_start|>assistant\n<think>\n\n</think>\n\n"
QWEN_END = "<|im_end|>\n"
QWEN_THINK = "<|im_start|>assistant\n<think>\n"

ALIASES = {"chatml": "qwen", "qwen3": "qwen", "qwen3.8": "qwen", "qwen3.5": "qwen", "mistral": "v7", "tekken": "v7"}
PLACEMENTS = ("end", "inline", "after", "start")
STOPS = {
    "qwen": ["<|im_end|>", "<|im_start|>", "<|endoftext|>"],
    "v7": ["</s>", "[INST]"],
    "v3": ["</s>", "[INST]"],
}


def scrub(text):
    return SPECIAL.sub("", str(text or ""))


def strip_thinking(text):
    text = THINK.sub("", str(text or ""))
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    if "<think>" in text:
        text = text.split("<think>", 1)[0]
    return text


class Format:
    def __init__(self, name="qwen", placement="end"):
        name = str(name or "qwen").strip().lower()
        name = ALIASES.get(name, name)
        if name not in STOPS:
            raise ValueError(f"unknown PROMPT_FORMAT {name!r}, use qwen, v7 or v3")
        self.name = name
        self.placement = placement if placement in PLACEMENTS else "end"
        self.stop = list(STOPS[name])

    def __repr__(self):
        return f"Format({self.name!r}, {self.placement!r})"

    def chat(self, system, turns, notes=None, reopen=False):
        system = scrub(system).strip()
        notes = scrub(notes).strip() if notes else None
        turns = [[r, scrub(t).strip()] for r, t in turns]
        if notes and self.placement == "start":
            system, notes = (system + "\n\n" + notes).strip(), None
        if self.name == "qwen":
            return self._qwen(system, turns, notes, reopen)
        return self._mistral(system, turns, notes, reopen)

    def _last_user(self, turns, notes):
        return max((i for i, (r, _) in enumerate(turns) if r == "user"), default=-1) if notes else -1

    def _qwen(self, system, turns, notes, reopen):
        last_user = self._last_user(turns, notes)
        out = [QWEN_SYS.format(system)] if system else []
        for i, (role, text) in enumerate(turns):
            if role == "user":
                if i == last_user and self.placement == "inline":
                    text = notes + "\n\n" + text
                if i == last_user and self.placement == "end":
                    out.append(QWEN_SYS.format(notes))
                out.append(QWEN_USER.format(text))
                if i == last_user and self.placement == "after":
                    out.append(QWEN_SYS.format(notes))
            else:
                out.append(QWEN_REPLY + text + QWEN_END)
        if reopen and turns and turns[-1][0] == "assistant":
            out[-1] = out[-1][: -len(QWEN_END)] + "\n"
        else:
            out.append(QWEN_REPLY)
        return "".join(out)

    def _mistral(self, system, turns, notes, reopen):
        v7 = self.name == "v7"
        last_user = self._last_user(turns, notes)
        inline = not v7 or self.placement == "inline"
        prompt = "[SYSTEM_PROMPT]" + system + "[/SYSTEM_PROMPT]" if v7 else ""
        for i, (role, text) in enumerate(turns):
            if role == "user":
                if i == last_user and inline:
                    text = notes + "\n\n" + text
                if i == last_user and v7 and self.placement == "end":
                    prompt += "[SYSTEM_PROMPT]" + notes + "[/SYSTEM_PROMPT]"
                prompt += "[INST]" + (system + "\n\n" if i == 0 and not v7 else "") + text + "[/INST]"
                if i == last_user and v7 and self.placement == "after":
                    prompt += "[SYSTEM_PROMPT]" + notes + "[/SYSTEM_PROMPT]"
            else:
                prompt += text + "</s>"
        if reopen and turns and turns[-1][0] == "assistant":
            prompt = prompt[: -len("</s>")] + "\n"
        return prompt

    def training_text(self, messages):
        system = ""
        if messages and messages[0]["role"] == "system":
            system, messages = messages[0]["content"], messages[1:]
        turns = [[m["role"], m["content"]] for m in messages]
        if not turns or turns[-1][0] != "assistant":
            raise ValueError("a training example has to end with one of her replies")
        if self.name == "qwen":
            return self.chat(system, turns)[: -len(QWEN_REPLY)].rstrip("\n")
        return self.chat(system, turns)

    def training_parts(self, messages, notes=None, learn=None):
        system = ""
        if messages and messages[0]["role"] == "system":
            system, messages = messages[0]["content"], messages[1:]
        turns = [[m["role"], m["content"]] for m in messages]
        if not turns or turns[-1][0] != "assistant":
            raise ValueError("a training example has to end with one of her replies")
        text = self.chat(system, turns, notes)
        if self.name == "qwen":
            text = text[: -len(QWEN_REPLY)].rstrip("\n")
            opener, closer = QWEN_REPLY, "<|im_end|>"
        else:
            opener, closer = "[/INST]", "</s>"
        n_replies = sum(1 for r, _ in turns if r == "assistant")
        want = set(range(n_replies)) if learn is None else {int(i) for i in learn}
        spans, pos, k = [], 0, 0
        while True:
            at = text.find(opener, pos)
            if at < 0:
                break
            start = at + len(opener)
            end = text.find(closer, start)
            if end < 0:
                break
            if k in want:
                spans.append((start, end + len(closer)))
            k, pos = k + 1, end + len(closer)
        if k != n_replies:
            raise ValueError(f"found {k} replies in the text, expected {n_replies}")
        return text, spans

    def response_parts(self):
        if self.name == "qwen":
            return "<|im_start|>user\n", "<|im_start|>assistant\n"
        return "[INST]", "[/INST]"

    @property
    def can_think(self):
        return self.name == "qwen"

    def instruct(self, system, user, think=False):
        system, user = scrub(system).strip(), scrub(user).strip()
        if self.name == "qwen":
            head = (QWEN_SYS.format(system) if system else "") + QWEN_USER.format(user)
            return head + (QWEN_THINK if think else QWEN_REPLY)
        if self.name == "v7":
            return f"[SYSTEM_PROMPT]{system}[/SYSTEM_PROMPT][INST]{user}[/INST]"
        return f"[INST]{system}\n\n{user}[/INST]"

    def after_thinking(self, prompt, thought):
        return prompt + scrub(thought).strip() + "\n</think>\n\n"

    def clean(self, text):
        text = strip_thinking(text)
        for s in self.stop:
            text = text.split(s, 1)[0]
        return SPECIAL.sub("", text)


def from_config(cfg):
    return Format(cfg.PROMPT_FORMAT, str(cfg.NOTES_PLACEMENT or "end").lower())
