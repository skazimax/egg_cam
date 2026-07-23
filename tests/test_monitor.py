import unittest
from pathlib import Path
from unittest.mock import patch

from egg_benchmark.monitor import monitor_rtsp


class FakeTracker:
    has_unconfirmed_candidates = True
    needs_warmup = False


class FakeMonitor:
    def __init__(self) -> None:
        self.tracker = FakeTracker()
        self.images: list[Path] = []

    def process_image(self, image_path: Path) -> int:
        self.images.append(image_path)
        return 0


class MonitorTest(unittest.TestCase):
    @patch("egg_benchmark.monitor.time.sleep")
    @patch("egg_benchmark.monitor.capture_rtsp_frame")
    def test_candidate_triggers_three_frame_burst(self, capture, sleep) -> None:
        capture.side_effect = [Path("one.jpg"), Path("two.jpg"), Path("three.jpg")]
        monitor = FakeMonitor()

        monitor_rtsp(
            monitor,  # type: ignore[arg-type]
            "rtsp://camera",
            Path("frames"),
            interval_seconds=300,
            max_frames=3,
            confirmation_burst_frames=3,
            confirmation_interval_seconds=5,
        )

        self.assertEqual(monitor.images, [Path("one.jpg"), Path("two.jpg"), Path("three.jpg")])
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [5, 5])


if __name__ == "__main__":
    unittest.main()
