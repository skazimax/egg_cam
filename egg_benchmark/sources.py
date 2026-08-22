from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
DEFAULT_RTSP_WARMUP_SECONDS = 4.0


def _read_warmed_rtsp_frame(stream, warmup_seconds: float):
    """Read until the RTSP decoder has received a complete keyframe."""
    deadline = time.monotonic() + max(0.0, warmup_seconds)
    frame = None
    while frame is None or time.monotonic() < deadline:
        ok, candidate = stream.read()
        if ok:
            frame = candidate
        else:
            time.sleep(0.05)
    if frame is None:
        raise RuntimeError("failed to read RTSP frame")
    return frame


def capture_rtsp_frame(
    rtsp_url: str,
    output_dir: Path,
    warmup_seconds: float = DEFAULT_RTSP_WARMUP_SECONDS,
    open_timeout_seconds: float | None = None,
    read_timeout_seconds: float | None = None,
) -> Path:
    import cv2

    output_dir.mkdir(parents=True, exist_ok=True)
    capture_params: list[int] = []
    if open_timeout_seconds is not None and open_timeout_seconds > 0:
        capture_params.extend(
            [
                cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                round(open_timeout_seconds * 1000),
            ]
        )
    if read_timeout_seconds is not None and read_timeout_seconds > 0:
        capture_params.extend(
            [
                cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                round(read_timeout_seconds * 1000),
            ]
        )
    stream = (
        cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG, capture_params)
        if capture_params
        else cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    )
    if not stream.isOpened():
        raise RuntimeError("could not open RTSP stream")
    try:
        frame = _read_warmed_rtsp_frame(stream, warmup_seconds)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        destination = output_dir / f"camera_{timestamp}.jpg"
        if not cv2.imwrite(str(destination), frame):
            raise RuntimeError(f"failed to write {destination}")
        return destination
    finally:
        stream.release()


def capture_rtsp_frame_guarded(
    rtsp_url: str,
    output_dir: Path,
    timeout_seconds: float,
    warmup_seconds: float = DEFAULT_RTSP_WARMUP_SECONDS,
    open_timeout_seconds: float = 15.0,
    read_timeout_seconds: float = 15.0,
) -> Path:
    """Capture in a disposable process so a native decoder hang is killable."""
    timeout_seconds = max(1.0, timeout_seconds)
    environment = os.environ.copy()
    environment["EGG_CAM_CAPTURE_RTSP_URL"] = rtsp_url
    command = [
        sys.executable,
        "-m",
        "egg_benchmark.capture_worker",
        "--output-dir",
        str(output_dir),
        "--warmup-seconds",
        str(max(0.0, warmup_seconds)),
        "--open-timeout-seconds",
        str(max(0.0, open_timeout_seconds)),
        "--read-timeout-seconds",
        str(max(0.0, read_timeout_seconds)),
    ]
    try:
        completed = subprocess.run(
            command,
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"RTSP capture timed out after {timeout_seconds:.1f}s"
        ) from None
    if completed.returncode != 0:
        raise RuntimeError("RTSP capture worker failed")
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("RTSP capture worker returned no frame path")
    image_path = Path(lines[-1])
    if not image_path.is_file():
        raise RuntimeError("RTSP capture worker did not create a frame")
    return image_path


def discover_images(path: Path) -> list[Path]:
    if path.is_file():
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            raise ValueError(f"unsupported image extension: {path.suffix}")
        return [path]
    if not path.is_dir():
        raise FileNotFoundError(path)
    return sorted(
        candidate
        for candidate in path.iterdir()
        if candidate.is_file() and candidate.suffix.lower() in IMAGE_SUFFIXES
    )


def capture_rtsp(
    rtsp_url: str,
    output_dir: Path,
    count: int,
    interval_seconds: float,
) -> list[Path]:
    import cv2

    output_dir.mkdir(parents=True, exist_ok=True)
    captured: list[Path] = []
    stream = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    if not stream.isOpened():
        raise RuntimeError("could not open RTSP stream")
    try:
        for index in range(count):
            if index == 0:
                frame = _read_warmed_rtsp_frame(
                    stream,
                    DEFAULT_RTSP_WARMUP_SECONDS,
                )
            else:
                ok, frame = stream.read()
                if not ok:
                    raise RuntimeError(f"failed to read RTSP frame {index + 1}")
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            destination = output_dir / f"camera_{timestamp}_{index + 1:03d}.jpg"
            if not cv2.imwrite(str(destination), frame):
                raise RuntimeError(f"failed to write {destination}")
            captured.append(destination)
            if index + 1 < count:
                time.sleep(interval_seconds)
    finally:
        stream.release()
    return captured
