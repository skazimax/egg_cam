import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from egg_benchmark.storage import EventStore
from egg_benchmark.types import Detection


class EventStoreTest(unittest.TestCase):
    def test_summary_counts_day_week_and_month(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(Path(directory) / "events.sqlite3")
            detection = Detection("egg", 0.9, [1, 2, 3, 4])
            first_ids = store.add_events(
                datetime(2026, 7, 23, 7, 0), Path("one.jpg"), [detection]
            )
            store.add_events(
                datetime(2026, 7, 21, 7, 0), Path("two.jpg"), [detection]
            )
            store.add_events(
                datetime(2026, 7, 5, 7, 0), Path("three.jpg"), [detection]
            )
            self.assertEqual(
                store.summary(datetime(2026, 7, 23, 12, 0)),
                {"today": 1, "yesterday": 0, "week": 2, "month": 3},
            )
            pending = store.pending_notifications()
            self.assertEqual(len(pending), 3)
            store.mark_notified(first_ids)
            self.assertEqual(len(store.pending_notifications()), 2)
            store.close()


if __name__ == "__main__":
    unittest.main()
