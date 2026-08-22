import unittest
from pathlib import Path
from unittest.mock import patch

from egg_benchmark.monitor import EggMonitor, monitor_rtsp


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
        self.collection_notifications: list[Path] = []
        self.camera_alerts: list[int] = []
        self.camera_recoveries: list[int] = []

    def process_image(
        self, image_path: Path, is_regular_frame: bool = True
    ) -> int:
        self.images.append((image_path, is_regular_frame))
        if self.empty_states:
            self.last_empty_candidate = self.empty_states.pop(0)
        return 0

    def confirm_empty_collection(self, image_path: Path) -> None:
        self.collection_resets += 1
        self.collection_notifications.append(image_path)
        self.last_empty_candidate = False

    def notify_camera_unavailable(
        self, consecutive_failures: int, error: Exception
    ) -> None:
        if consecutive_failures >= 3:
            self.camera_alerts.append(consecutive_failures)

    def notify_camera_recovered(self, consecutive_failures: int) -> bool:
        self.camera_recoveries.append(consecutive_failures)
        return True


class CollectionTracker:
    def __init__(self) -> None:
        self.session_peak = 5
        self.reset_calls = 0

    def reset_session(self) -> None:
        self.reset_calls += 1
        self.session_peak = 0


class CollectionStore:
    def __init__(self) -> None:
        self.metadata: dict[str, str] = {}

    def set_metadata(self, key: str, value: str) -> None:
        self.metadata[key] = value

    def get_metadata(self, key: str) -> str | None:
        return self.metadata.get(key)


class CollectionTelegram:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.photos: list[tuple[Path, str]] = []
        self.messages: list[str] = []

    def send_photo(self, image_path: Path, caption: str) -> None:
        self.photos.append((image_path, caption))
        if self.fail:
            raise RuntimeError("telegram unavailable")

    def send_message(self, message: str) -> None:
        self.messages.append(message)
        if self.fail:
            raise RuntimeError("telegram unavailable")


class MonitorTest(unittest.TestCase):
    def build_collection_monitor(
        self, telegram: CollectionTelegram, tracker: CollectionTracker
    ) -> tuple[EggMonitor, CollectionStore]:
        store = CollectionStore()
        monitor = EggMonitor(
            adapter=object(),  # type: ignore[arg-type]
            tracker=tracker,  # type: ignore[arg-type]
            store=store,  # type: ignore[arg-type]
            telegram=telegram,  # type: ignore[arg-type]
            output_dir=Path("runtime"),
        )
        monitor.last_empty_candidate = True
        return monitor, store

    def test_collection_photo_is_sent_before_session_reset(self) -> None:
        tracker = CollectionTracker()
        telegram = CollectionTelegram()
        monitor, store = self.build_collection_monitor(telegram, tracker)

        monitor.confirm_empty_collection(Path("final-empty.jpg"))

        self.assertEqual(
            telegram.photos,
            [(Path("final-empty.jpg"), "🥚 Яйца собраны — обнуляю сессию.")],
        )
        self.assertEqual(tracker.reset_calls, 1)
        self.assertEqual(store.metadata["inventory_session_peak"], "0")

    def test_telegram_failure_preserves_collection_session(self) -> None:
        tracker = CollectionTracker()
        monitor, store = self.build_collection_monitor(
            CollectionTelegram(fail=True), tracker
        )

        with self.assertRaisesRegex(RuntimeError, "telegram unavailable"):
            monitor.confirm_empty_collection(Path("final-empty.jpg"))

        self.assertEqual(tracker.reset_calls, 0)
        self.assertEqual(tracker.session_peak, 5)
        self.assertEqual(store.metadata, {})

    def test_camera_health_alert_is_deduplicated_and_recovered(self) -> None:
        tracker = CollectionTracker()
        telegram = CollectionTelegram()
        monitor, store = self.build_collection_monitor(telegram, tracker)

        monitor.notify_camera_unavailable(1, RuntimeError("rtsp"))
        monitor.notify_camera_unavailable(2, RuntimeError("rtsp"))
        self.assertEqual(telegram.messages, [])

        monitor.notify_camera_unavailable(3, RuntimeError("rtsp"))
        monitor.notify_camera_unavailable(4, RuntimeError("rtsp"))
        self.assertEqual(len(telegram.messages), 1)
        self.assertEqual(store.metadata["camera_unavailable_alert_sent"], "1")

        self.assertTrue(monitor.notify_camera_recovered(4))
        self.assertEqual(len(telegram.messages), 2)
        self.assertEqual(store.metadata["camera_unavailable_alert_sent"], "0")

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
        self.assertEqual(monitor.collection_notifications, [Path("final.jpg")])
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
        self.assertEqual(monitor.collection_notifications, [])
        self.assertNotIn(60, clock.sleeps)

    @patch("egg_benchmark.monitor.capture_rtsp_frame_guarded")
    def test_camera_failure_alert_and_recovery_are_emitted_once(
        self, capture
    ) -> None:
        capture.side_effect = [
            RuntimeError("rtsp unavailable"),
            RuntimeError("rtsp unavailable"),
            RuntimeError("rtsp unavailable"),
            Path("recovered.jpg"),
        ]
        monitor = FakeMonitor(FakeTracker())
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
                max_frames=1,
                camera_capture_timeout_seconds=45,
            )

        self.assertEqual(monitor.camera_alerts, [3])
        self.assertEqual(monitor.camera_recoveries, [3])
        self.assertEqual(monitor.images, [(Path("recovered.jpg"), True)])


if __name__ == "__main__":
    unittest.main()
