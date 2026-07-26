from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import yaml

from .models import build_adapter
from .monitor import EggMonitor, monitor_rtsp, replay_images
from .reporting import save_annotated, write_reports
from .sources import capture_rtsp, discover_images
from .storage import EventStore
from .telegram import TelegramClient
from .tracker import EggTracker
from .types import ModelResult


PROJECT_DIR = Path(__file__).resolve().parent.parent


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        value = yaml.safe_load(file) or {}
    return value


def load_ground_truth(path: Path | None) -> dict[str, int]:
    if path is None or not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as file:
        return {
            row["image"]: int(row["egg_count"])
            for row in csv.DictReader(file)
            if row.get("image") and row.get("egg_count")
        }


def run_benchmark(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    images = discover_images(args.input)
    if not images:
        print(f"No images found in {args.input}", file=sys.stderr)
        return 2

    names = [item.strip() for item in args.models.split(",") if item.strip()]
    results: list[ModelResult] = []
    run_dir = args.output / time.strftime("%Y%m%d_%H%M%S")

    for name in names:
        print(f"[{name}] loading model...", flush=True)
        adapter = build_adapter(name, config.get("models", {}).get(name, {}))
        try:
            adapter.load()
        except Exception as exc:
            print(f"[{name}] load failed: {exc}", file=sys.stderr, flush=True)
            for image_path in images:
                from PIL import Image

                with Image.open(image_path) as image:
                    width, height = image.size
                results.append(
                    ModelResult(
                        model=name,
                        image=str(image_path),
                        width=width,
                        height=height,
                        latency_seconds=0.0,
                        error=f"model load failed: {exc}",
                    )
                )
            continue

        for image_path in images:
            print(f"[{name}] {image_path.name}", flush=True)
            try:
                result = adapter.predict(image_path)
            except Exception as exc:
                from PIL import Image

                with Image.open(image_path) as image:
                    width, height = image.size
                result = ModelResult(
                    model=name,
                    image=str(image_path),
                    width=width,
                    height=height,
                    latency_seconds=0.0,
                    error=f"prediction failed: {exc}",
                )
            results.append(result)
            annotated = run_dir / "annotated" / name / f"{image_path.stem}.jpg"
            save_annotated(result, annotated)
            print(
                f"[{name}] eggs={result.count}, time={result.latency_seconds:.2f}s"
                + (f", error={result.error}" if result.error else ""),
                flush=True,
            )
        del adapter

    write_reports(results, run_dir, load_ground_truth(args.ground_truth))
    print(f"Report: {run_dir / 'report.md'}")
    return 0


def capture(args: argparse.Namespace) -> int:
    rtsp_url = args.rtsp_url or os.environ.get("CAMERA_RTSP_URL")
    if not rtsp_url:
        print(
            "Set CAMERA_RTSP_URL or pass --rtsp-url. Avoid putting credentials in shell history.",
            file=sys.stderr,
        )
        return 2
    frames = capture_rtsp(rtsp_url, args.output, args.count, args.interval)
    print(f"Captured {len(frames)} frames in {args.output}")
    return 0


def send_telegram_test(args: argparse.Namespace) -> int:
    telegram = TelegramClient.from_environment()
    if not telegram.enabled:
        print(
            "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.",
            file=sys.stderr,
        )
        return 2
    if not args.image.is_file():
        print(f"Image not found: {args.image}", file=sys.stderr)
        return 2

    image_to_send = args.image
    caption = args.caption
    try:
        if args.detect:
            config = load_config(args.config)
            monitor_config = config.get("monitor", {})
            model_name = str(monitor_config.get("model", "owlv2"))
            adapter = build_adapter(
                model_name, config.get("models", {}).get(model_name, {})
            )
            print(f"[{model_name}] loading model...", flush=True)
            adapter.load()
            result = adapter.predict(args.image)
            if result.error:
                raise RuntimeError(result.error)
            save_annotated(
                result,
                args.output,
                highlighted=result.detections,
                label_mode=str(
                    monitor_config.get("annotation_label_mode", "none")
                ),
                line_width=int(
                    monitor_config.get("annotation_line_width", 2)
                ),
            )
            image_to_send = args.output
            caption = f"{caption}\n🥚 Найдено яиц: {result.count}"

        telegram.send_photo(image_to_send, caption)
    except Exception as exc:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        status = f" (HTTP {status_code})" if status_code is not None else ""
        print(
            f"Telegram test failed{status}: {type(exc).__name__}",
            file=sys.stderr,
        )
        return 1

    print(f"Telegram test photo sent: {image_to_send}")
    return 0


def run_monitor(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config(args.config)
    monitor_config = config.get("monitor", {})
    model_name = str(monitor_config.get("model", "owlv2"))
    adapter = build_adapter(
        model_name, config.get("models", {}).get(model_name, {})
    )
    print(f"[{model_name}] loading model...", flush=True)
    adapter.load()

    store = EventStore(args.state_dir / "events.sqlite3")
    stored_peak = store.get_metadata("inventory_session_peak")

    def stored_int(key: str) -> int:
        try:
            return int(store.get_metadata(key) or 0)
        except ValueError:
            logging.getLogger(__name__).warning("invalid integer metadata: %s", key)
            return 0

    tracker = EggTracker(
        confirm_frames=int(monitor_config.get("confirm_frames", 2)),
        warmup_frames=int(monitor_config.get("warmup_frames", 2)),
        max_missed_frames=int(monitor_config.get("max_missed_frames", 1)),
        iou_threshold=float(monitor_config.get("iou_threshold", 0.20)),
        max_center_distance=float(
            monitor_config.get("max_center_distance", 0.035)
        ),
        session_peak=stored_int("inventory_session_peak") if stored_peak is not None else None,
        peak_regular_hits=stored_int("inventory_peak_regular_hits"),
        empty_regular_checks=stored_int("inventory_empty_regular_checks"),
        collection_arm_checks=int(monitor_config.get("collection_arm_checks", 3)),
        collection_confirm_checks=int(
            monitor_config.get("collection_confirm_checks", 6)
        ),
    )
    telegram = TelegramClient.from_environment()
    if not args.dry_run and not telegram.enabled:
        print(
            "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID or pass --dry-run.",
            file=sys.stderr,
        )
        return 2

    monitor = EggMonitor(
        adapter=adapter,
        tracker=tracker,
        store=store,
        telegram=telegram,
        output_dir=args.state_dir,
        dry_run=args.dry_run,
        report_hour=int(monitor_config.get("report_hour", 8)),
        annotation_label_mode=str(
            monitor_config.get("annotation_label_mode", "none")
        ),
        annotation_line_width=int(
            monitor_config.get("annotation_line_width", 2)
        ),
    )
    try:
        if args.input is not None:
            replay_images(monitor, discover_images(args.input))
            return 0
        rtsp_url = args.rtsp_url or os.environ.get("CAMERA_RTSP_URL")
        if not rtsp_url:
            print(
                "Set CAMERA_RTSP_URL, pass --rtsp-url, or use --input.",
                file=sys.stderr,
            )
            return 2
        monitor_rtsp(
            monitor,
            rtsp_url,
            args.state_dir / "frames",
            interval_seconds=args.interval,
            max_frames=args.max_frames,
            confirmation_burst_frames=int(
                monitor_config.get("confirmation_burst_frames", 3)
            ),
            confirmation_interval_seconds=float(
                monitor_config.get("confirmation_interval_seconds", 5.0)
            ),
        )
        return 0
    except KeyboardInterrupt:
        print("Monitoring stopped.")
        return 0
    finally:
        store.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark local egg detection models")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="run models on one image or a directory")
    run.add_argument("--input", type=Path, required=True)
    run.add_argument(
        "--models",
        default="yolo_world,grounding_dino,owlv2,moondream2",
        help="comma-separated model adapters",
    )
    run.add_argument(
        "--config", type=Path, default=PROJECT_DIR / "config.example.yaml"
    )
    run.add_argument("--output", type=Path, default=PROJECT_DIR / "outputs")
    run.add_argument(
        "--ground-truth",
        type=Path,
        default=PROJECT_DIR / "data/ground_truth.csv",
        help="optional CSV with image,egg_count columns",
    )
    run.set_defaults(handler=run_benchmark)

    grab = subparsers.add_parser("capture", help="capture reproducible RTSP frames")
    grab.add_argument("--rtsp-url", help="prefer CAMERA_RTSP_URL to avoid shell history")
    grab.add_argument("--count", type=int, default=10)
    grab.add_argument("--interval", type=float, default=300.0)
    grab.add_argument("--output", type=Path, default=PROJECT_DIR / "data/input")
    grab.set_defaults(handler=capture)

    watch = subparsers.add_parser(
        "monitor", help="detect and publish newly confirmed eggs"
    )
    watch.add_argument(
        "--config", type=Path, default=PROJECT_DIR / "config.example.yaml"
    )
    watch.add_argument(
        "--input", type=Path, help="replay an image or directory instead of RTSP"
    )
    watch.add_argument("--rtsp-url", help="prefer CAMERA_RTSP_URL")
    watch.add_argument("--interval", type=float, default=300.0)
    watch.add_argument("--max-frames", type=int)
    watch.add_argument("--dry-run", action="store_true")
    watch.add_argument(
        "--state-dir", type=Path, default=PROJECT_DIR / "runtime"
    )
    watch.set_defaults(handler=run_monitor)

    telegram_test = subparsers.add_parser(
        "telegram-test", help="send one test photo to Telegram"
    )
    telegram_test.add_argument(
        "--image",
        type=Path,
        default=PROJECT_DIR / "data/input/coop_sample.png",
    )
    telegram_test.add_argument(
        "--caption",
        default="Тест egg monitor: отправка работает",
    )
    telegram_test.add_argument(
        "--detect",
        action="store_true",
        help="run the configured detector and send an annotated image",
    )
    telegram_test.add_argument(
        "--config", type=Path, default=PROJECT_DIR / "config.example.yaml"
    )
    telegram_test.add_argument(
        "--output",
        type=Path,
        default=PROJECT_DIR / "runtime/telegram-test/annotated.jpg",
    )
    telegram_test.set_defaults(handler=send_telegram_test)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
