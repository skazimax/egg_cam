import unittest
from pathlib import Path
from unittest.mock import patch

from egg_benchmark.monitor import monitor_rtsp


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeTracker:
    def __init__(
        self,
        has_unconfirmed_candidates: bool = False,
        needs_warmup: bool = False,
    ) -> None:
        self.has_unconfirmed_candidates = has_unconfirmed_candidates
        self.needs_warmup = needs_warmup


class FakeMonitor:
    def __init__(
        self,
        tracker: FakeTracker,
        empty_states: list[bool] | None = None,
    ) -> None:
        self.tracker = tracker
        self.empty_states = list(empty_states or [])
        self.last_empty_candidate = False
        self.images: list[tuple[Path, bool]] = []
        self.collection_resets = 0

    def process_image(
        self, image_path: Path, is_regular_frame: bool = True
    ) -> int:
        self.images.append((image_path, is_regular_frame))
        if self.empty_states:
            self.last_empty_candidate = self.empty_states.pop(0)
        return 0

    def confirm_empty_collection(self) -> None:
        self.collection_resets += 1
        self.last_empty_candidate = False


class MonitorTest(unittest.TestCase):
    @patch("egg_benchmark.monitor.capture_rtsp_frame")
    def test_egg_candidate_captures_configured_confirmation_batch(
        self, capture
    ) -> None:
        capture.side_effect = [
            Path("regular.jpg"),
            Path("confirm-1.jpg"),
            Path("confirm-2.jpg"),
            Path("confirm-3.jpg"),
        ]
        monitor = FakeMonitor(FakeTracker(has_unconfirmed_candidates=True))
        clock = FakeClock()

        with (
            patch("egg_benchmark.monitor.time.monotonic", clock.monotonic),
            patch("egg_benchmark.monitor.time.sleep", clock.sleep),
        ):
            monitor_rtsp(
                monitor,  # type: ignore[arg-type]
                "rtsp://camera",
                Path("frames"),
                interval_seconds=300,
                max_frames=4,
                egg_confirmation_frames=3,
                egg_confirmation_interval_seconds=5,
            )

        self.assertEqual(
            monitor.images,
            [
                (Path("regular.jpg"), True),
                (Path("confirm-1.jpg"), False),
                (Path("confirm-2.jpg"), False),
                (Path("confirm-3.jpg"), False),
            ],
        )
        self.assertEqual(clock.sleeps, [5, 5])

    @patch("egg_benchmark.monitor.capture_rtsp_frame")
    def test_empty_candidate_requires_burst_and_delayed_final_frame(
        self, capture
    ) -> None:
        capture.side_effect = [
            Path("regular.jpg"),
            Path("empty-1.jpg"),
            Path("empty-2.jpg"),
            Path("empty-3.jpg"),
            Path("final.jpg"),
        ]
        monitor = FakeMonitor(
            FakeTracker(),
            empty_states=[True, True, True, True, True],
        )
        clock = FakeClock()

        with (
            patch("egg_benchmark.monitor.time.monotonic", clock.monotonic),
            patch("egg_benchmark.monitor.time.sleep", clock.sleep),
        ):
            monitor_rtsp(
                monitor,  # type: ignore[arg-type]
                "rtsp://camera",
                Path("frames"),
                interval_seconds=300,
                max_frames=5,
                empty_confirmation_frames=3,
                empty_confirmation_interval_seconds=5,
                empty_final_delay_seconds=60,
            )

        self.assertEqual(monitor.collection_resets, 1)
        self.assertEqual(clock.sleeps, [5, 5, 60])

    @patch("egg_benchmark.monitor.capture_rtsp_frame")
    def test_nonempty_confirmation_cancels_empty_reset(self, capture) -> None:
        capture.side_effect = [
            Path("regular.jpg"),
            Path("empty-1.jpg"),
            Path("egg-visible.jpg"),
            Path("empty-3.jpg"),
        ]
        monitor = FakeMonitor(
            FakeTracker(),
            empty_states=[True, True, False, True],
        )
        clock = FakeClock()

        with (
            patch("egg_benchmark.monitor.time.monotonic", clock.monotonic),
            patch("egg_benchmark.monitor.time.sleep", clock.sleep),
        ):
            monitor_rtsp(
                monitor,  # type: ignore[arg-type]
                "rtsp://camera",
                Path("frames"),
                interval_seconds=300,
                max_frames=4,
                empty_confirmation_frames=3,
                empty_confirmation_interval_seconds=5,
                empty_final_delay_seconds=60,
            )

        self.assertEqual(monitor.collection_resets, 0)
        self.assertNotIn(60, clock.sleeps)


if __name__ == "__main__":
    unittest.main()
