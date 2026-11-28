import asyncio
import bisect
import sqlite3
import time

from mitski.core import logs
from mitski.core.component import Component
from mitski.core.text import cut
from mitski.core.texts import say, wording
from mitski.memory.dates import DAY, said_ago
from mitski.memory.heuristics import words

log = logs.get("chatlog")

EMBED_EVERY = 20
EMBED_BATCH = 32
MAX_ROWS = 300_000
NEAR_SEC = 15 * 60
SKIP_RECENT_SEC = 20 * 60
CANDIDATES = 20
AROUND = 2
MIN_COSINE = 0.38
RRF = 60
MAX_TEXT = 500

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, channel INTEGER, guild INTEGER, "
    "author INTEGER, name TEXT, text TEXT, t REAL, mine INTEGER, vec BLOB)",
    "CREATE INDEX IF NOT EXISTS by_author ON messages (author, t)",
    "CREATE INDEX IF NOT EXISTS by_channel ON messages (channel, id)",
)


def pack(vec):
    import numpy as np

    return np.asarray(vec, dtype=np.float16).tobytes()


def unpack_all(blobs):
    import numpy as np

    return np.stack([np.frombuffer(b, dtype=np.float16).astype(np.float32) for b in blobs])


class ChatLog(Component):
    def __init__(self, app):
        super().__init__(app)
        self.path = app.cfg.paths.data_file("chatlog.db")
        self.db = None
        self.pending = []
        self.lock = asyncio.Lock()

    @property
    def on(self):
        return bool(self.cfg.MEMORY and self.cfg.CHAT_HISTORY)

    def open(self):
        if not self.on or self.db is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        for sql in SCHEMA:
            self.db.execute(sql)
        self.db.commit()
        self.pending = [r[0] for r in self.db.execute("SELECT id FROM messages WHERE vec IS NULL")]

    def close(self):
        if self.db is not None:
            self.db.commit()
            self.db.close()
            self.db = None

    def count(self):
        return self.db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] if self.db else 0

    def status(self):
        if not self.on:
            return "off"
        return f"{self.count()} messages kept" + ("" if self.memory.embed.active else ", keywords only")

    def keep(self, msg):
        if not self.on or self.db is None:
            return
        author = msg.author
        if self.memory.opted_out(author) or (author.id in self.cfg.ignored and author.id != self.me.id):
            return
        text = cut(self.messages.text(msg), MAX_TEXT)
        if not text:
            return
        mine = self.me is not None and author.id == self.me.id
        guild = getattr(msg, "guild", None)
        name = "" if mine else self.messages.call(author)
        t = msg.created_at.timestamp() if getattr(msg, "created_at", None) else time.time()
        cur = self.db.execute(
            "INSERT OR IGNORE INTO messages (id, channel, guild, author, name, text, t, mine) VALUES (?,?,?,?,?,?,?,?)",
            (msg.id, msg.channel.id, getattr(guild, "id", None), author.id, name, text, t, int(mine)),
        )
        if cur.rowcount:
            self.pending.append(msg.id)

    def forget(self, user_id):
        if self.db is None:
            return 0
        n = self.db.execute("DELETE FROM messages WHERE author = ?", (int(user_id),)).rowcount
        self.db.commit()
        return n

    async def run(self):
        while True:
            await asyncio.sleep(EMBED_EVERY)
            if self.db is None:
                continue
            try:
                await self.embed_pending()
                self.prune()
            except Exception:
                log.warning("chat history upkeep failed", exc_info=True)

    async def embed_pending(self):
        embed = self.memory.embed
        if not (embed.active and self.pending):
            if self.db is not None:
                self.db.commit()
            return
        async with self.lock:
            while self.pending:
                batch, self.pending = self.pending[:EMBED_BATCH], self.pending[EMBED_BATCH:]
                marks = ",".join("?" * len(batch))
                rows = self.db.execute(f"SELECT id, text FROM messages WHERE id IN ({marks})", batch).fetchall()
                if not rows:
                    continue
                try:
                    vecs = await embed._call([text for _, text in rows])
                except Exception as e:
                    embed._failed(e)
                    self.pending = batch + self.pending
                    return
                self.db.executemany(
                    "UPDATE messages SET vec = ? WHERE id = ?",
                    [(pack(v), i) for (i, _), v in zip(rows, vecs, strict=False)],
                )
                self.db.commit()
                await asyncio.sleep(0)

    def prune(self, now=None):
        now = now or time.time()
        days = self.cfg.CHAT_HISTORY_DAYS
        if days:
            self.db.execute("DELETE FROM messages WHERE t < ?", (now - days * DAY,))
        extra = self.count() - MAX_ROWS
        if extra > 0:
            self.db.execute("DELETE FROM messages WHERE id IN (SELECT id FROM messages ORDER BY t LIMIT ?)", (extra,))
        self.db.commit()

    def _candidates(self, user_id, now):
        theirs = self.db.execute(
            "SELECT id, channel, author, name, text, t, mine, vec FROM messages WHERE author = ? AND t < ?",
            (user_id, now - SKIP_RECENT_SEC),
        ).fetchall()
        if not theirs:
            return []
        times = {}
        for row in theirs:
            times.setdefault(row[1], []).append(row[5])
        for ts in times.values():
            ts.sort()
        channels = list(times)
        marks = ",".join("?" * len(channels))
        hers = self.db.execute(
            f"SELECT id, channel, author, name, text, t, mine, vec FROM messages WHERE mine = 1 AND channel IN ({marks})",
            channels,
        ).fetchall()

        def near(row):
            ts = times[row[1]]
            i = bisect.bisect_left(ts, row[5])
            return any(0 <= j < len(ts) and abs(ts[j] - row[5]) <= NEAR_SEC for j in (i - 1, i))

        return theirs + [r for r in hers if r[5] < now - SKIP_RECENT_SEC and near(r)]

    async def search(self, user, query, k=4, now=None):
        if not self.on or self.db is None or user is None or not (query or "").strip():
            return []
        now = now or time.time()
        await self.embed_pending()
        rows = self._candidates(user.id, now)
        if not rows:
            return []
        q = words(query)
        kw = sorted(
            ((len(q & words(r[4])), i) for i, r in enumerate(rows) if q & words(r[4])), key=lambda x: (-x[0], -x[1])
        )
        ranks = {}
        for rank, (_, i) in enumerate(kw):
            ranks[i] = ranks.get(i, 0.0) + 1 / (RRF + rank)
        cos = {}
        embedded = [i for i, r in enumerate(rows) if r[7]]
        qv = await self.memory.embed.query(cut(query, 1200)) if embedded and self.memory.embed.active else None
        if qv is not None:
            import numpy as np

            sims = unpack_all([rows[i][7] for i in embedded]) @ np.asarray(qv, dtype=np.float32)
            order = sorted(range(len(embedded)), key=lambda j: -sims[j])
            for rank, j in enumerate(order[:200]):
                cos[embedded[j]] = float(sims[j])
                if sims[j] >= MIN_COSINE:
                    ranks[embedded[j]] = ranks.get(embedded[j], 0.0) + 1 / (RRF + rank)
        top = sorted(ranks, key=lambda i: -ranks[i])[:CANDIDATES]
        if not top:
            return []
        reranker = getattr(self.memory, "rerank", None)
        if reranker is not None and reranker.active:
            got = await reranker.rank(query, [self._line(rows[i], user) for i in top], k)
            if got:
                top = [top[i] for i, _ in got[:k]]
        hits = top[:k]
        return self._snippets([rows[i] for i in hits], user, now)

    def _line(self, row, user):
        return f"{'you' if row[6] else (row[3] or self.messages.call(user))}: {row[4]}"

    def _snippets(self, hits, user, now):
        out, seen = [], set()
        for row in sorted(hits, key=lambda r: r[5]):
            if row[0] in seen:
                continue
            around = self.db.execute(
                "SELECT id, channel, author, name, text, t, mine, vec FROM ("
                "SELECT * FROM messages WHERE channel = ? AND id <= ? ORDER BY id DESC LIMIT ?) "
                "UNION SELECT id, channel, author, name, text, t, mine, vec FROM ("
                "SELECT * FROM messages WHERE channel = ? AND id > ? ORDER BY id LIMIT ?) ORDER BY id",
                (row[1], row[0], AROUND + 1, row[1], row[0], AROUND),
            ).fetchall()
            around = [r for r in around if abs(r[5] - row[5]) <= NEAR_SEC and r[0] not in seen]
            seen.update(r[0] for r in around)
            where = self._where(row[1])
            lines = " / ".join(f"{'you' if r[6] else r[3] or '?'}: {cut(r[4], 160)}" for r in around)
            out.append(say("memory.chat_snippet", when=said_ago(row[5], now), where=where, lines=lines))
        return out

    def _where(self, channel_id):
        channel = self.app.get_channel(channel_id)
        if channel is None or getattr(channel, "guild", None) is None:
            return wording("memory.chat_in_dms")
        return f"#{channel.name}"
