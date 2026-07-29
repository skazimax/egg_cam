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

    def test_candidate_requires_all_three_additional_confirmations(self) -> None:
        tracker = EggTracker(confirm_frames=4, warmup_frames=1)
        tracker.update([], 1000, 1000)

        self.assertEqual(tracker.update([egg(300, 300)], 1000, 1000), [])
        self.assertEqual(tracker.update([egg(301, 300)], 1000, 1000), [])
        self.assertEqual(tracker.update([egg(302, 301)], 1000, 1000), [])
        self.assertEqual(
            len(tracker.update([egg(303, 301)], 1000, 1000)),
            1,
        )

    def test_reappearing_eggs_are_not_counted_twice_within_session(self) -> None:
        tracker = EggTracker(
            confirm_frames=2,
            warmup_frames=2,
            max_missed_frames=0,
        )
        tracker.update([], 1000, 1000)
        tracker.update([], 1000, 1000)
        pair = [egg(300, 300), egg(400, 300)]
        tracker.update(pair, 1000, 1000, is_regular_frame=True)
        self.assertEqual(
            len(tracker.update(pair, 1000, 1000, is_regular_frame=False)), 2
        )

        # Missing detections never change the session peak by themselves.
        for _ in range(10):
            tracker.update([], 1000, 1000, is_regular_frame=True)
        tracker.update(pair, 1000, 1000, is_regular_frame=True)
        self.assertEqual(
            tracker.update(pair, 1000, 1000, is_regular_frame=False), []
        )

        five = pair + [egg(500, 300), egg(600, 300), egg(700, 300)]
        tracker.update(five, 1000, 1000, is_regular_frame=True)
        self.assertEqual(
            len(tracker.update(five, 1000, 1000, is_regular_frame=False)), 3
        )
        self.assertEqual(tracker.session_peak, 5)

    def test_explicit_session_reset_allows_same_count_again(self) -> None:
        tracker = EggTracker(confirm_frames=1, warmup_frames=1)
        tracker.update([], 1000, 1000)
        self.assertEqual(len(tracker.update([egg(300, 300)], 1000, 1000)), 1)

        tracker.reset_session()

        self.assertEqual(tracker.session_peak, 0)
        self.assertEqual(tracker.tracks, [])
        self.assertEqual(len(tracker.update([egg(300, 300)], 1000, 1000)), 1)

    def test_restored_peak_suppresses_duplicate_after_restart(self) -> None:
        tracker = EggTracker(
            confirm_frames=2,
            warmup_frames=2,
            max_missed_frames=0,
            session_peak=2,
        )
        pair = [egg(300, 300), egg(400, 300)]
        tracker.update(pair, 1000, 1000)
        self.assertEqual(tracker.update(pair, 1000, 1000), [])
        three = pair + [egg(500, 300)]
        tracker.update(three, 1000, 1000)
        self.assertEqual(len(tracker.update(three, 1000, 1000)), 1)


if __name__ == "__main__":
    unittest.main()
