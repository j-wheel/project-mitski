import ast
from pathlib import Path

import pytest

from mitski.core import texts
from mitski.core.texts import TextError, fill, fill_all, slots, wording

CODE = Path(texts.__file__).resolve().parent.parent
FOLDERS = (CODE, CODE.parent / "evals", CODE.parent / "training")


def uses():
    out = []
    for path in (p for folder in FOLDERS for p in folder.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            if node.func.id not in ("say", "wording") or not node.args:
                continue
            key = node.args[0]
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                given = {k.arg for k in node.keywords if k.arg} if node.func.id == "say" else None
                unpacked = any(k.arg is None for k in node.keywords)
                out.append((path.relative_to(CODE.parent), node.lineno, key.value, given, unpacked))
    return out


def test_every_text_the_code_asks_for_exists():
    missing = []
    for where, line, key, _, _ in uses():
        try:
            wording(key)
        except TextError:
            missing.append(f"{where}:{line} {key}")
    assert not missing, missing


def test_every_placeholder_a_text_uses_is_given_by_the_code():
    gaps = []
    for where, line, key, given, unpacked in uses():
        if given is None or unpacked:
            continue
        text = wording(key)
        if isinstance(text, str) and slots(text) - given:
            gaps.append(f"{where}:{line} {key} needs {sorted(slots(text) - given)}")
    assert not gaps, gaps


def test_no_text_in_the_prompts_folder_is_unused():
    used = {key for _, _, key, _, _ in uses()}
    roots = {key.split(".")[0] + "." + key.split(".")[1] for key in used if key.count(".") >= 1}
    unused = []
    for category, entries in texts._all().items():
        for name in entries:
            if f"{category}.{name}" not in used and f"{category}.{name}" not in roots:
                unused.append(f"{category}.{name}")
    assert not unused, unused


def test_placeholders_fill_and_json_stays_as_written():
    assert fill('{"a": {"b": 1}} hi {name}', name="anna") == '{"a": {"b": 1}} hi anna'
    assert fill("say {{name}} literally", name="x") == "say {name} literally"
    assert fill_all({"a": ["{x}", 2], "b": "{x}!"}, x="y") == {"a": ["y", 2], "b": "y!"}


def test_a_missing_placeholder_says_which():
    with pytest.raises(TextError, match="name"):
        fill("hi {name}")


def test_an_override_folder_replaces_only_what_it_has(tmp_path, monkeypatch):
    (tmp_path / "guard.yaml").write_text('injection: "nope {name}"\n', encoding="utf-8")
    monkeypatch.setattr(texts, "folder", lambda: tmp_path)
    texts._all.cache_clear()
    try:
        assert wording("guard.injection") == "nope {name}"
        assert wording("guard.ai_talk").startswith("{name} is talking to you")
    finally:
        texts._all.cache_clear()
