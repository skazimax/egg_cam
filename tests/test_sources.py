import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from egg_benchmark.sources import capture_rtsp_frame_guarded


class GuardedCaptureTest(unittest.TestCase):
    def test_timeout_becomes_camera_failure_without_url_in_error(self) -> None:
        secret_url = "rtsp://user:secret@camera/stream"
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "egg_benchmark.sources.subprocess.run",
                side_effect=subprocess.TimeoutExpired("capture", 12),
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError, "RTSP capture timed out after 12.0s"
            ) as raised:
                capture_rtsp_frame_guarded(
                    secret_url, Path(directory), timeout_seconds=12
                )

        self.assertNotIn(secret_url, str(raised.exception))
        self.assertNotIn("secret", str(raised.exception))

    def test_success_returns_worker_frame(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "camera.jpg"
            image_path.write_bytes(b"frame")
            completed = SimpleNamespace(
                returncode=0,
                stdout=f"{image_path}\n",
                stderr="",
            )
            with patch(
                "egg_benchmark.sources.subprocess.run",
                return_value=completed,
            ) as run:
                result = capture_rtsp_frame_guarded(
                    "rtsp://camera",
                    Path(directory),
                    timeout_seconds=45,
                    open_timeout_seconds=10,
                    read_timeout_seconds=11,
                )

        self.assertEqual(result, image_path)
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["timeout"], 45)
        self.assertEqual(kwargs["env"]["EGG_CAM_CAPTURE_RTSP_URL"], "rtsp://camera")
        self.assertNotIn("rtsp://camera", run.call_args.args[0])

    def test_worker_failure_is_sanitized(self) -> None:
        completed = SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="rtsp://user:secret@camera/stream",
        )
        with patch(
            "egg_benchmark.sources.subprocess.run", return_value=completed
        ):
            with self.assertRaisesRegex(
                RuntimeError, "RTSP capture worker failed"
            ) as raised:
                capture_rtsp_frame_guarded(
                    "rtsp://user:secret@camera/stream",
                    Path("frames"),
                    timeout_seconds=45,
                )

        self.assertNotIn("secret", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
