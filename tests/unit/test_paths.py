from pathlib import Path

from mitski.paths import DEFAULTS, Paths, render


def test_without_a_paths_file_everything_is_in_the_project(tmp_path):
    paths = Paths(tmp_path)
    assert paths.data == tmp_path / "data"
    assert paths.sounds == tmp_path / "mp3"
    assert paths.data_file("memory.db") == tmp_path / "data" / "memory.db"


def test_paths_yaml_moves_things_and_relative_ones_stay_in_the_project(tmp_path, monkeypatch):
    monkeypatch.setenv("MITSKI_HOME", str(tmp_path))
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "paths.yaml").write_text(
        'data: "D:/mitski-data"\nsounds: "audio"\nllm_lora: ""\napplio: "~/Applio"\n', encoding="utf-8"
    )
    paths = Paths.discover()
    assert paths.data == Path("D:/mitski-data")
    assert paths.sounds == tmp_path / "audio"
    assert paths.get("llm_lora") is None
    assert paths.get("applio") == Path.home() / "Applio"


def test_a_missing_paths_file_is_written_with_every_name(tmp_path, monkeypatch):
    monkeypatch.setenv("MITSKI_HOME", str(tmp_path))
    Paths.discover()
    text = (tmp_path / "config" / "paths.yaml").read_text(encoding="utf-8")
    assert text == render()
    assert all(f"{name}:" in text for name in DEFAULTS)


def test_a_bare_llama_server_name_is_found_on_path(tmp_path, monkeypatch):
    monkeypatch.setattr("mitski.paths.shutil.which", lambda name: f"/opt/bin/{name}")
    assert Paths(tmp_path).get("llama_server") == Path("/opt/bin/llama-server")
    monkeypatch.setattr("mitski.paths.shutil.which", lambda name: None)
    assert Paths(tmp_path).get("llama_server") == tmp_path / "llama-server"


def test_the_template_points_nowhere_personal():
    text = render()
    assert ":/" not in text and "~" not in text.split("\n", 2)[2]


def test_unknown_names_are_refused(tmp_path):
    try:
        Paths(tmp_path).get("nope")
    except KeyError:
        return
    raise AssertionError("expected a KeyError")
