import json
import sqlite3
import time
from pathlib import Path

from mitski.core import logs
from mitski.core.storage import JsonFile

log = logs.get("memory")

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS people (id TEXT PRIMARY KEY, data TEXT NOT NULL, last_seen REAL, updated REAL)",
    "CREATE TABLE IF NOT EXISTS store (key TEXT PRIMARY KEY, data TEXT NOT NULL)",
)
SELF_KEY = "self"
DEFAULT_SELF = {"facts": [], "next_id": 1}


def _dump(data):
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


class Batch:
    def __init__(self, upserts, deletes, own):
        self.upserts = upserts
        self.deletes = deletes
        self.own = own

    def __bool__(self):
        return bool(self.upserts or self.deletes or self.own is not None)


class PeopleDB:
    def __init__(self, path, legacy_people=None, legacy_self=None):
        self.path = Path(path)
        self.legacy_people = Path(legacy_people) if legacy_people else None
        self.legacy_self = Path(legacy_self) if legacy_self else None
        self.conn = None
        self.written = {}
        self.written_own = None

    def open(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        for statement in SCHEMA:
            self.conn.execute(statement)

    def close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def backup(self, path):
        path = Path(path)
        if path.exists():
            return False
        target = sqlite3.connect(path)
        try:
            self.conn.backup(target)
        finally:
            target.close()
        return True

    def load(self):
        if self.conn is None:
            self.open()
        self._migrate_json()
        people = {uid: json.loads(data) for uid, data in self.conn.execute("SELECT id, data FROM people")}
        row = self.conn.execute("SELECT data FROM store WHERE key = ?", (SELF_KEY,)).fetchone()
        own = json.loads(row[0]) if row else json.loads(json.dumps(DEFAULT_SELF))
        self.written = {uid: _dump(d) for uid, d in people.items()}
        self.written_own = _dump(own)
        return people, own

    def _migrate_json(self):
        if self.conn.execute("SELECT 1 FROM people LIMIT 1").fetchone() is not None:
            return
        people = JsonFile(self.legacy_people, {}).load() if self.legacy_people and self.legacy_people.exists() else {}
        own = (
            JsonFile(self.legacy_self, DEFAULT_SELF).load() if self.legacy_self and self.legacy_self.exists() else None
        )
        if not people and own is None:
            return
        self.write(self._batch_for(people, own, {}, None))
        for legacy in (self.legacy_people, self.legacy_self):
            if legacy and legacy.exists():
                legacy.replace(legacy.with_name(legacy.name + ".migrated"))
        log.info("moved %d people from %s into %s", len(people), self.legacy_people.name, self.path.name)

    def changes(self, people, own):
        return self._batch_for(people, own, self.written, self.written_own)

    @staticmethod
    def _batch_for(people, own, written, written_own):
        now = time.time()
        upserts = []
        for uid, d in people.items():
            text = _dump(d)
            if written.get(uid) != text:
                upserts.append((uid, text, d.get("last_seen"), now))
        deletes = [uid for uid in written if uid not in people]
        own_text = _dump(own) if own is not None else None
        return Batch(upserts, deletes, own_text if own_text != written_own else None)

    def write(self, batch):
        if self.conn is None:
            self.open()
        with self.conn:
            self.conn.execute("BEGIN")
            self.conn.executemany(
                "INSERT INTO people (id, data, last_seen, updated) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data = excluded.data, last_seen = excluded.last_seen, "
                "updated = excluded.updated",
                batch.upserts,
            )
            self.conn.executemany("DELETE FROM people WHERE id = ?", [(uid,) for uid in batch.deletes])
            if batch.own is not None:
                self.conn.execute(
                    "INSERT INTO store (key, data) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET data = excluded.data",
                    (SELF_KEY, batch.own),
                )

    def committed(self, batch):
        for uid, text, _, _ in batch.upserts:
            self.written[uid] = text
        for uid in batch.deletes:
            self.written.pop(uid, None)
        if batch.own is not None:
            self.written_own = batch.own
