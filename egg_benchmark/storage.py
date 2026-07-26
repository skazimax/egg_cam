from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from .types import Detection


class EventStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS egg_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                detected_at REAL NOT NULL,
                image_path TEXT NOT NULL,
                score REAL NOT NULL,
                x1 REAL NOT NULL,
                y1 REAL NOT NULL,
                x2 REAL NOT NULL,
                y2 REAL NOT NULL,
                notification_sent INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        columns = {
            str(row[1])
            for row in self.connection.execute("PRAGMA table_info(egg_events)")
        }
        if "notification_sent" not in columns:
            self.connection.execute(
                "ALTER TABLE egg_events ADD COLUMN notification_sent INTEGER NOT NULL DEFAULT 0"
            )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        self.connection.commit()

    def add_events(
        self, detected_at: datetime, image_path: Path, detections: list[Detection]
    ) -> list[int]:
        event_ids: list[int] = []
        for detection in detections:
            cursor = self.connection.execute(
                """
                INSERT INTO egg_events
                (detected_at, image_path, score, x1, y1, x2, y2)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    detected_at.timestamp(),
                    str(image_path),
                    detection.score,
                    *detection.box_xyxy,
                ),
            )
            event_ids.append(int(cursor.lastrowid))
        self.connection.commit()
        return event_ids

    def pending_notifications(self) -> list[tuple[list[int], datetime, Path]]:
        rows = self.connection.execute(
            """
            SELECT GROUP_CONCAT(id), detected_at, image_path
            FROM egg_events
            WHERE notification_sent = 0
            GROUP BY detected_at, image_path
            ORDER BY detected_at
            """
        ).fetchall()
        return [
            (
                [int(value) for value in str(ids).split(",")],
                datetime.fromtimestamp(float(detected_at)).astimezone(),
                Path(str(image_path)),
            )
            for ids, detected_at, image_path in rows
        ]

    def mark_notified(self, event_ids: list[int]) -> None:
        self.connection.executemany(
            "UPDATE egg_events SET notification_sent = 1 WHERE id = ?",
            [(event_id,) for event_id in event_ids],
        )
        self.connection.commit()

    def count_between(self, start: datetime, end: datetime) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) FROM egg_events WHERE detected_at >= ? AND detected_at < ?",
            (start.timestamp(), end.timestamp()),
        ).fetchone()
        return int(row[0])

    def summary(self, now: datetime) -> dict[str, int]:
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = midnight + timedelta(days=1)
        yesterday = midnight - timedelta(days=1)
        week_start = midnight - timedelta(days=midnight.weekday())
        month_start = midnight.replace(day=1)
        return {
            "today": self.count_between(midnight, tomorrow),
            "yesterday": self.count_between(yesterday, midnight),
            "week": self.count_between(week_start, tomorrow),
            "month": self.count_between(month_start, tomorrow),
        }

    def get_metadata(self, key: str) -> str | None:
        row = self.connection.execute(
            "SELECT value FROM metadata WHERE key = ?", (key,)
        ).fetchone()
        return None if row is None else str(row[0])

    def set_metadata(self, key: str, value: str) -> None:
        self.set_metadata_many({key: value})

    def set_metadata_many(self, values: dict[str, str]) -> None:
        with self.connection:
            self.connection.executemany(
                """INSERT INTO metadata(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                values.items(),
            )

    def close(self) -> None:
        self.connection.close()
