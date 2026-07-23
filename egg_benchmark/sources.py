from __future__ import annotations

import time
from pathlib import Path


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def capture_rtsp_frame(rtsp_url: str, output_dir: Path) -> Path:
    import cv2

    output_dir.mkdir(parents=True, exist_ok=True)
    stream = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    if not stream.isOpened():
        raise RuntimeError("could not open RTSP stream")
    try:
        frame = None
        for _ in range(3):
            ok, candidate = stream.read()
            if ok:
                frame = candidate
        if frame is None:
            raise RuntimeError("failed to read RTSP frame")
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        destination = output_dir / f"camera_{timestamp}.jpg"
        if not cv2.imwrite(str(destination), frame):
            raise RuntimeError(f"failed to write {destination}")
        return destination
    finally:
        stream.release()


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
