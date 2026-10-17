"""SQLite store for signal items, source watermarks, and run logs."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from signal_engine.models import SignalItem


class SignalStore:
    """Manages SQLite persistence and stable-ID deduplication."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS items (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    body TEXT NOT NULL,
                    published_at TEXT,
                    engagement REAL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    fetched_at TEXT NOT NULL,
                    filtered_by TEXT,
                    decision TEXT,
                    in_digest TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_items_source ON items(source);
                CREATE INDEX IF NOT EXISTS idx_items_published_at ON items(published_at);
                CREATE INDEX IF NOT EXISTS idx_items_filtered_by ON items(filtered_by);

                CREATE TABLE IF NOT EXISTS sources (
                    source TEXT PRIMARY KEY,
                    last_fetched_at TEXT NOT NULL,
                    last_fetched_count INTEGER NOT NULL DEFAULT 0,
                    last_new_count INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    stats TEXT NOT NULL DEFAULT '{}'
                );
                """
            )

    def has_id(self, item_id: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone()
        return row is not None

    def upsert_items(self, source_name: str, items: list[SignalItem]) -> tuple[int, int]:
        """Insert new items (deduping by stable id). Returns (fetched_count, new_inserted_count)."""
        now_iso = datetime.now(timezone.utc).isoformat()
        new_count = 0
        with self.conn:
            for item in items:
                exists = self.conn.execute(
                    "SELECT 1 FROM items WHERE id = ?", (item.id,)
                ).fetchone()
                if exists:
                    continue
                pub_iso = (
                    item.published_at.astimezone(timezone.utc).isoformat()
                    if item.published_at
                    else None
                )
                self.conn.execute(
                    """
                    INSERT INTO items (
                        id, source, title, url, body, published_at,
                        engagement, metadata, fetched_at, filtered_by, decision, in_digest
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.id,
                        item.source,
                        item.title,
                        item.url,
                        (item.body or "")[:4000],
                        pub_iso,
                        item.engagement,
                        json.dumps(item.metadata or {}, ensure_ascii=False),
                        now_iso,
                        item.filtered_by,
                        json.dumps(item.decision, ensure_ascii=False) if item.decision else None,
                        item.in_digest,
                    ),
                )
                new_count += 1

            self.conn.execute(
                """
                INSERT INTO sources (source, last_fetched_at, last_fetched_count, last_new_count)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    last_fetched_at = excluded.last_fetched_at,
                    last_fetched_count = excluded.last_fetched_count,
                    last_new_count = excluded.last_new_count
                """,
                (source_name, now_iso, len(items), new_count),
            )
        return len(items), new_count

    def get_unfiltered_items(self) -> list[SignalItem]:
        """Return items that have not been dropped by a code filter (`filtered_by IS NULL`)."""
        rows = self.conn.execute(
            "SELECT * FROM items WHERE filtered_by IS NULL AND in_digest IS NULL ORDER BY published_at DESC"
        ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def get_all_items(self) -> list[SignalItem]:
        rows = self.conn.execute(
            "SELECT * FROM items ORDER BY published_at DESC"
        ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def mark_filtered(self, item_id: str, reason: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE items SET filtered_by = ? WHERE id = ?",
                (reason, item_id),
            )

    def reset_filters_and_decisions(self) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE items SET filtered_by = NULL, decision = NULL WHERE in_digest IS NULL"
            )

    def save_decision(self, item_id: str, decision: dict[str, Any], filtered_by: str | None = None) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE items SET decision = ?, filtered_by = COALESCE(?, filtered_by) WHERE id = ?",
                (json.dumps(decision, ensure_ascii=False), filtered_by, item_id),
            )

    def get_surviving_for_reading(self) -> list[SignalItem]:
        """Return items that survived code filters and the decision pass (keep or unsure)."""
        rows = self.conn.execute(
            "SELECT * FROM items WHERE filtered_by IS NULL AND in_digest IS NULL"
        ).fetchall()
        items = [self._row_to_item(r) for r in rows]

        def sort_key(it: SignalItem) -> tuple[int, float, float]:
            dec = it.decision or {}
            route = dec.get("route", "unsure")
            route_rank = 2 if route == "keep" else 1
            rel = float(dec.get("relevance", 0.5))
            new_prob = float(dec.get("new", 0.5))
            return (route_rank, rel, new_prob)

        items.sort(key=sort_key, reverse=True)
        return items

    def mark_in_digest(self, item_ids: list[str], digest_date: str) -> None:
        with self.conn:
            for item_id in item_ids:
                self.conn.execute(
                    "UPDATE items SET in_digest = ? WHERE id = ?",
                    (digest_date, item_id),
                )

    def log_run(self, started_at: str, stats: dict[str, Any]) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.conn:
            self.conn.execute(
                "INSERT INTO runs (started_at, completed_at, stats) VALUES (?, ?, ?)",
                (started_at, now_iso, json.dumps(stats, ensure_ascii=False)),
            )

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> SignalItem:
        pub = datetime.fromisoformat(row["published_at"]) if row["published_at"] else None
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
        dec = json.loads(row["decision"]) if row["decision"] else None
        return SignalItem(
            id=row["id"],
            source=row["source"],
            title=row["title"],
            url=row["url"],
            body=row["body"],
            published_at=pub,
            engagement=row["engagement"],
            metadata=meta,
            filtered_by=row["filtered_by"],
            decision=dec,
            in_digest=row["in_digest"],
        )

    def close(self) -> None:
        self.conn.close()
