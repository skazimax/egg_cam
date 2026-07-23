import unittest

from egg_benchmark.tracker import EggTracker
from egg_benchmark.types import Detection


def egg(x: float, y: float) -> Detection:
    return Detection("egg", 0.9, [x, y, x + 20, y + 25])


class EggTrackerTest(unittest.TestCase):
    def test_existing_egg_becomes_baseline(self) -> None:
        tracker = EggTracker(confirm_frames=2, warmup_frames=2)
        self.assertTrue(tracker.needs_warmup)
        self.assertEqual(tracker.update([egg(100, 100)], 1000, 1000), [])
        self.assertEqual(tracker.update([egg(102, 101)], 1000, 1000), [])
        self.assertFalse(tracker.needs_warmup)
        self.assertEqual(tracker.update([egg(101, 102)], 1000, 1000), [])

    def test_new_egg_is_emitted_once_after_confirmation(self) -> None:
        tracker = EggTracker(confirm_frames=2, warmup_frames=2)
        tracker.update([], 1000, 1000)
        tracker.update([], 1000, 1000)
        self.assertEqual(tracker.update([egg(300, 300)], 1000, 1000), [])
        self.assertTrue(tracker.has_unconfirmed_candidates)
        found = tracker.update([egg(302, 301)], 1000, 1000)
        self.assertEqual(len(found), 1)
        self.assertFalse(tracker.has_unconfirmed_candidates)
        self.assertEqual(tracker.update([egg(301, 302)], 1000, 1000), [])

    def test_removed_egg_can_be_counted_again(self) -> None:
        tracker = EggTracker(
            confirm_frames=2, warmup_frames=2, max_missed_frames=0
        )
        tracker.update([], 1000, 1000)
        tracker.update([], 1000, 1000)
        tracker.update([egg(300, 300)], 1000, 1000)
        self.assertEqual(len(tracker.update([egg(300, 300)], 1000, 1000)), 1)
        tracker.update([], 1000, 1000)
        tracker.update([egg(300, 300)], 1000, 1000)
        self.assertEqual(len(tracker.update([egg(300, 300)], 1000, 1000)), 1)


if __name__ == "__main__":
    unittest.main()
