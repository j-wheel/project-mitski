import json
import sqlite3

from mitski.memory.database import PeopleDB


def db(tmp_path):
    return PeopleDB(tmp_path / "memory.db", tmp_path / "memory.json", tmp_path / "self.json")


def test_round_trip_writes_only_what_changed(tmp_path):
    store = db(tmp_path)
    people, own = store.load()
    assert people == {} and own == {"facts": [], "next_id": 1}
    people["1"] = {"name": "anna", "last_seen": 5}
    people["2"] = {"name": "bob", "last_seen": 6}
    batch = store.changes(people, own)
    assert len(batch.upserts) == 2 and batch.own is None
    store.write(batch)
    store.committed(batch)
    people["2"]["name"] = "bobby"
    batch = store.changes(people, own)
    assert [u[0] for u in batch.upserts] == ["2"]
    store.write(batch)
    store.committed(batch)
    again, _ = db(tmp_path).load()
    assert again == {"1": {"name": "anna", "last_seen": 5}, "2": {"name": "bobby", "last_seen": 6}}


def test_deletes_reach_the_database(tmp_path):
    store = db(tmp_path)
    people, own = store.load()
    people["1"] = {"name": "anna"}
    batch = store.changes(people, own)
    store.write(batch)
    store.committed(batch)
    del people["1"]
    batch = store.changes(people, own)
    assert batch.deletes == ["1"]
    store.write(batch)
    store.committed(batch)
    assert sqlite3.connect(tmp_path / "memory.db").execute("SELECT COUNT(*) FROM people").fetchone() == (0,)


def test_old_json_files_are_migrated_once(tmp_path):
    (tmp_path / "memory.json").write_text(json.dumps({"7": {"name": "zoe"}}), encoding="utf-8")
    (tmp_path / "self.json").write_text(json.dumps({"facts": [{"id": 1}], "next_id": 2}), encoding="utf-8")
    people, own = db(tmp_path).load()
    assert people == {"7": {"name": "zoe"}}
    assert own["next_id"] == 2
    assert not (tmp_path / "memory.json").exists()
    assert (tmp_path / "memory.json.migrated").exists()
    assert db(tmp_path).load()[0] == people
