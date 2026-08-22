from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .sources import capture_rtsp_frame


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Isolated RTSP frame capture")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--warmup-seconds", type=float, required=True)
    parser.add_argument("--open-timeout-seconds", type=float, required=True)
    parser.add_argument("--read-timeout-seconds", type=float, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    rtsp_url = os.environ.pop("EGG_CAM_CAPTURE_RTSP_URL", None)
    if not rtsp_url:
        print("RTSP capture URL is missing", file=sys.stderr)
        return 2
    try:
        image_path = capture_rtsp_frame(
            rtsp_url,
            args.output_dir,
            warmup_seconds=args.warmup_seconds,
            open_timeout_seconds=args.open_timeout_seconds,
            read_timeout_seconds=args.read_timeout_seconds,
        )
    except Exception as exc:
        print(f"RTSP capture failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(image_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
