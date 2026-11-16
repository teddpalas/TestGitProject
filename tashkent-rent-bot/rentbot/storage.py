"""Durable, revision-aware SQLite outbox.

The application runs one delivery worker. Network sends happen outside SQLite
transactions. Delivery is at-least-once: a crash after Telegram accepts a send
but before mark_sent() can cause a retry. Telegram does not expose an idempotency
key for Bot API sends, so claiming exactly-once delivery would be misleading.
"""

from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Iterator


def _timestamp(value: datetime) -> float:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must include a timezone")
    return value.timestamp()


class Store:
    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), timeout=30, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS items (
                key TEXT PRIMARY KEY,
                revision TEXT NOT NULL,
                tier TEXT NOT NULL CHECK(tier IN ('quiet', 'loud', 'reject')),
                payload TEXT NOT NULL,
                due_at REAL NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending', 'sent', 'rejected')),
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT
            );
            CREATE INDEX IF NOT EXISTS items_due ON items(status, due_at);
            CREATE TABLE IF NOT EXISTS versions (
                key TEXT NOT NULL,
                revision TEXT NOT NULL,
                tier TEXT NOT NULL,
                PRIMARY KEY (key, revision)
            );
            CREATE TABLE IF NOT EXISTS sent_history (
                key TEXT NOT NULL,
                revision TEXT NOT NULL,
                tier TEXT NOT NULL,
                PRIMARY KEY (key, revision)
            );
            CREATE INDEX IF NOT EXISTS sent_history_key_tier
                ON sent_history(key, tier);
            """
        )

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        self._db.execute("BEGIN IMMEDIATE")
        try:
            yield self._db
        except BaseException:
            self._db.rollback()
            raise
        else:
            self._db.commit()

    def get_meta(self, key: str, default=None):
        row = self._db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError("metadata values must be strings")
        with self._transaction() as db:
            db.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def enqueue(
        self, key: str, revision: str, tier: str, payload: dict, due: datetime
    ) -> bool:
        """Queue a new revision; return False for a duplicate/suppressed item.

        Revisions must include any derived criteria and the decision, not only
        raw post text. A repeated pending revision preserves its original due
        time and retry state. Any delivered loud revision suppresses subsequent
        notifications for that listing key. Quiet revisions may be updated.
        """
        if not key or not revision:
            raise ValueError("key and revision must not be empty")
        if tier not in {"quiet", "loud"}:
            raise ValueError("only quiet or loud items can be enqueued")
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dictionary")
        due_at = _timestamp(due)
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
        with self._transaction() as db:
            if db.execute(
                "SELECT 1 FROM sent_history WHERE key=? AND (revision=? OR tier='loud')",
                (key, revision),
            ).fetchone():
                return False
            current = db.execute(
                "SELECT revision FROM items WHERE key=?", (key,)
            ).fetchone()
            if current and current["revision"] == revision:
                return False
            db.execute(
                "INSERT INTO versions(key, revision, tier) VALUES (?, ?, ?) "
                "ON CONFLICT(key, revision) DO NOTHING",
                (key, revision, tier),
            )
            db.execute(
                """
                INSERT INTO items(key, revision, tier, payload, due_at, status)
                VALUES (?, ?, ?, ?, ?, 'pending')
                ON CONFLICT(key) DO UPDATE SET
                    revision=excluded.revision, tier=excluded.tier,
                    payload=excluded.payload, due_at=excluded.due_at,
                    status='pending', attempts=0, last_error=NULL
                """,
                (key, revision, tier, encoded, due_at),
            )
        return True

    def reject(self, key: str, revision: str) -> None:
        """Remember the current rejected revision and cancel any queued version."""
        if not key or not revision:
            raise ValueError("key and revision must not be empty")
        with self._transaction() as db:
            db.execute(
                """
                INSERT INTO items(key, revision, tier, payload, due_at, status)
                VALUES (?, ?, 'reject', '{}', 0, 'rejected')
                ON CONFLICT(key) DO UPDATE SET
                    revision=excluded.revision, tier='reject', payload='{}',
                    due_at=0, status='rejected', attempts=0, last_error=NULL
                """,
                (key, revision),
            )

    def due(self, now: datetime, limit: int = 20) -> list[dict]:
        """Peek at due items. Call mark_sent() or retry() after each send attempt."""
        if not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        rows = self._db.execute(
            """
            SELECT key, revision, tier, payload, attempts, due_at, last_error
            FROM items AS item
            WHERE status='pending' AND due_at<=?
              AND NOT EXISTS (
                SELECT 1 FROM sent_history AS sent
                WHERE sent.key=item.key
                  AND (sent.revision=item.revision OR sent.tier='loud')
              )
            ORDER BY CASE tier WHEN 'loud' THEN 0 ELSE 1 END, due_at, key
            LIMIT ?
            """,
            (_timestamp(now), limit),
        ).fetchall()
        return [dict(row) | {"payload": json.loads(row["payload"])} for row in rows]

    def mark_sent(self, key: str, revision: str) -> None:
        """Record delivery without overwriting a newer queued/rejected revision."""
        with self._transaction() as db:
            version = db.execute(
                "SELECT tier FROM versions WHERE key=? AND revision=?", (key, revision)
            ).fetchone()
            if version is None:
                return
            db.execute(
                "INSERT INTO sent_history(key, revision, tier) VALUES (?, ?, ?) "
                "ON CONFLICT(key, revision) DO NOTHING",
                (key, revision, version["tier"]),
            )
            db.execute(
                "UPDATE items SET status='sent', last_error=NULL "
                "WHERE key=? AND revision=? AND status='pending'",
                (key, revision),
            )

    def retry(self, key: str, revision: str, when: datetime, error: str) -> None:
        """Reschedule only the attempted revision, preserving a newer update."""
        with self._transaction() as db:
            db.execute(
                "UPDATE items SET due_at=?, attempts=attempts+1, last_error=? "
                "WHERE key=? AND revision=? AND status='pending'",
                (_timestamp(when), str(error)[:1000], key, revision),
            )

    def counts(self) -> dict[str, int]:
        pending = self._db.execute(
            """
            SELECT COUNT(*) FROM items AS item
            WHERE status='pending' AND NOT EXISTS (
                SELECT 1 FROM sent_history AS sent WHERE sent.key=item.key
                AND (sent.revision=item.revision OR sent.tier='loud')
            )
            """
        ).fetchone()[0]
        sent = dict(self._db.execute(
            "SELECT tier, COUNT(*) FROM sent_history GROUP BY tier"
        ).fetchall())
        rejected = self._db.execute(
            "SELECT COUNT(*) FROM items WHERE status='rejected'"
        ).fetchone()[0]
        return {
            "pending": pending,
            "sent": sum(sent.values()),
            "loud_sent": sent.get("loud", 0),
            "quiet_sent": sent.get("quiet", 0),
            "rejected": rejected,
        }

    def close(self) -> None:
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
