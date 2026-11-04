import pytest
import yaml

from mitski.config import ConfigError, Settings
from mitski.config.schema import OPTIONS, SECRET_KEYS
from mitski.config.settings import coerce, repeated_keys, yaml_key_span
from mitski.config.template import render_config, render_keys


def test_repeated_keys_are_found():
    text = 'STYLE_NOTE: "a"\nMEMORY: true\n# STYLE_NOTE: not this one\n  NESTED: 1\nSTYLE_NOTE: "b"\nA: 1\nA: 2\nNESTED: 3\n'
    assert repeated_keys(text) == ["A", "STYLE_NOTE"]


@pytest.mark.parametrize(
    ("key", "raw", "expected"),
    [
        ("MEMORY", "yes", True),
        ("MEMORY", "off", False),
        ("MEMORY", "maybe", OPTIONS["MEMORY"].default),
        ("MAX_TOKENS", "300", 300),
        ("MAX_TOKENS", "lots", OPTIONS["MAX_TOKENS"].default),
        ("TEMPERATURE", "0.7", 0.7),
        ("CHANNELS", 123, [123]),
        ("MAX_TOKENS", None, OPTIONS["MAX_TOKENS"].default),
        ("NOT_AN_OPTION", "raw", "raw"),
    ],
)
def test_coerce(key, raw, expected):
    assert coerce(key, raw) == expected


@pytest.mark.parametrize(
    ("text", "key", "span"),
    [
        ("A: 1\nB: 2\n", "B", (1, 2)),
        ("A: [1,\n  2]\nB: 3", "A", (0, 2)),
        ("A:\n  - 1\n  - 2\nB: 3", "A", (0, 3)),
        ("A: 1", "B", None),
    ],
)
def test_yaml_key_span(text, key, span):
    assert yaml_key_span(text.split("\n"), key) == span


def test_template_matches_the_schema():
    values = yaml.safe_load(render_config())
    assert set(values) == set(OPTIONS)
    for key, option in OPTIONS.items():
        assert values[key] == option.default, key
    assert set(yaml.safe_load(render_keys())) == set(SECRET_KEYS)


def test_first_run_writes_both_files_and_stops(paths):
    with pytest.raises(ConfigError, match="put your token"):
        Settings.load(paths)
    assert paths.config.exists() and paths.keys.exists()


def test_secrets_move_out_of_the_main_config(paths):
    paths.config_dir.mkdir()
    paths.config.write_text("TOKEN: abc\nMAX_TOKENS: 200\n", encoding="utf-8")
    cfg = Settings.load(paths)
    assert cfg.TOKEN == "abc"
    assert cfg.MAX_TOKENS == 200
    assert "TOKEN" not in yaml.safe_load(paths.config.read_text(encoding="utf-8"))
    assert yaml.safe_load(paths.keys.read_text(encoding="utf-8"))["TOKEN"] == "abc"


def test_save_list_keeps_the_rest_of_the_file(paths):
    paths.config_dir.mkdir()
    paths.config.write_text("# mine\nCHANNELS: [1, 2]\nMAX_TOKENS: 250 # keep\n", encoding="utf-8")
    paths.keys.write_text("TOKEN: t\n", encoding="utf-8")
    cfg = Settings.load(paths)
    cfg.save_list("CHANNELS", [2, 3])
    text = paths.config.read_text(encoding="utf-8")
    assert text.startswith("# mine\nCHANNELS: [2, 3]")
    assert "MAX_TOKENS: 250 # keep" in text
    assert cfg.saved_list("CHANNELS") == [2, 3]


def test_unknown_options_raise_on_access(make_cfg):
    cfg = make_cfg()
    with pytest.raises(AttributeError, match="no config option"):
        cfg.__getattr__("NOPE")
    assert cfg.get("NOPE", 5) == 5


def test_live_sets_come_from_the_lists(make_cfg):
    cfg = make_cfg(CHANNELS=["5", 6], IGNORE_USERS=[7], SLEEP_EXCLUDE=[8])
    assert (cfg.channels, cfg.ignored, cfg.sleep_exclude) == ({5, 6}, {7}, {8})


def test_broken_yaml_is_a_config_error(paths):
    paths.config_dir.mkdir()
    paths.config.write_text("A: [1,\n", encoding="utf-8")
    paths.keys.write_text("", encoding="utf-8")
    with pytest.raises(ConfigError, match="isn't valid yaml"):
        Settings.load(paths)
