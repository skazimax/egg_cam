from __future__ import annotations

import logging
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .models import ModelAdapter
from .reporting import save_annotated
from .sources import capture_rtsp_frame
from .storage import EventStore
from .telegram import TelegramClient
from .tracker import EggTracker


LOGGER = logging.getLogger(__name__)


class EggMonitor:
    def __init__(
        self,
        adapter: ModelAdapter,
        tracker: EggTracker,
        store: EventStore,
        telegram: TelegramClient,
        output_dir: Path,
        dry_run: bool = False,
        report_hour: int = 8,
        annotation_label_mode: str = "none",
        annotation_line_width: int = 2,
    ) -> None:
        self.adapter = adapter
        self.tracker = tracker
        self.store = store
        self.telegram = telegram
        self.output_dir = output_dir
        self.dry_run = dry_run
        self.report_hour = report_hour
        self.annotation_label_mode = annotation_label_mode
        self.annotation_line_width = annotation_line_width
        self._dry_report_date: str | None = None

    def process_image(
        self,
        image_path: Path,
        now: datetime | None = None,
        is_regular_frame: bool = True,
    ) -> int:
        now = now or datetime.now().astimezone()
        self.send_pending_notifications(now)
        result = self.adapter.predict(image_path)
        if result.error:
            raise RuntimeError(result.error)
        new_eggs = self.tracker.update(
            result.detections,
            result.width,
            result.height,
            is_regular_frame=is_regular_frame,
        )
        self.store.set_metadata_many(
            {
                "inventory_session_peak": str(self.tracker.session_peak),
                "inventory_peak_regular_hits": str(self.tracker.peak_regular_hits),
                "inventory_empty_regular_checks": str(
                    self.tracker.empty_regular_checks
                ),
            }
        )
        LOGGER.info(
            "frame=%s visible=%d session_peak=%d new=%d latency=%.2fs",
            image_path.name,
            result.count,
            self.tracker.session_peak,
            len(new_eggs),
            result.latency_seconds,
        )
        if self.tracker.last_collection_reset:
            LOGGER.info("egg collection confirmed; inventory session reset")
        if new_eggs:
            timestamp = now.strftime("%Y%m%d_%H%M%S_%f")
            original = self.output_dir / "events" / f"egg_{timestamp}.jpg"
            annotated = self.output_dir / "events" / f"egg_{timestamp}_annotated.jpg"
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(image_path, original)
            save_annotated(
                result,
                annotated,
                highlighted=new_eggs,
                label_mode=self.annotation_label_mode,
                line_width=self.annotation_line_width,
            )
            event_ids = self.store.add_events(now, annotated, new_eggs)
            if self.dry_run:
                LOGGER.info("dry-run new egg photo: %s", annotated)
                self.store.mark_notified(event_ids)
        self.send_pending_notifications(now)
        self.send_daily_report_if_due(now)
        return len(new_eggs)

    def send_pending_notifications(self, now: datetime) -> None:
        if self.dry_run:
            return
        for event_ids, detected_at, image_path in self.store.pending_notifications():
            summary = self.store.summary(now)
            caption = (
                f"🥚 Новых яиц: {len(event_ids)}\n"
                f"Сегодня: {summary['today']}\n"
                f"Время: {detected_at:%d.%m.%Y %H:%M}"
            )
            self.telegram.send_photo(image_path, caption)
            self.store.mark_notified(event_ids)

    def send_daily_report_if_due(self, now: datetime) -> None:
        report_date = now.date().isoformat()
        if now.hour < self.report_hour:
            return
        if self.store.get_metadata("last_daily_report") == report_date:
            return
        if self._dry_report_date == report_date:
            return
        summary = self.store.summary(now)
        message = (
            f"📊 Яйца на {now:%d.%m.%Y}\n"
            f"Вчера: {summary['yesterday']}\n"
            f"Сегодня: {summary['today']}\n"
            f"С начала недели: {summary['week']}\n"
            f"С начала месяца: {summary['month']}"
        )
        if self.dry_run:
            LOGGER.info("dry-run daily report: %s", message.replace("\n", "; "))
            self._dry_report_date = report_date
            return
        self.telegram.send_message(message)
        self.store.set_metadata("last_daily_report", report_date)


def monitor_rtsp(
    monitor: EggMonitor,
    rtsp_url: str,
    frames_dir: Path,
    interval_seconds: float,
    max_frames: int | None = None,
    confirmation_burst_frames: int = 3,
    confirmation_interval_seconds: float = 5.0,
) -> None:
    processed = 0
    while max_frames is None or processed < max_frames:
        started = time.monotonic()
        try:
            image_path = capture_rtsp_frame(rtsp_url, frames_dir)
            new_eggs = monitor.process_image(image_path)
            processed += 1
            if (
                new_eggs == 0
                and (
                    monitor.tracker.needs_warmup
                    or monitor.tracker.has_unconfirmed_candidates
                )
                and confirmation_burst_frames > 1
            ):
                LOGGER.info(
                    "new candidate: starting %d-frame confirmation burst at %.1fs interval",
                    confirmation_burst_frames,
                    confirmation_interval_seconds,
                )
                for _ in range(confirmation_burst_frames - 1):
                    if max_frames is not None and processed >= max_frames:
                        break
                    time.sleep(confirmation_interval_seconds)
                    confirmation_path = capture_rtsp_frame(rtsp_url, frames_dir)
                    monitor.process_image(
                        confirmation_path, is_regular_frame=False
                    )
                    processed += 1
        except Exception:
            LOGGER.exception("monitoring iteration failed")
        remaining = interval_seconds - (time.monotonic() - started)
        if remaining > 0 and (max_frames is None or processed < max_frames):
            time.sleep(remaining)


def replay_images(monitor: EggMonitor, images: Iterable[Path]) -> None:
    for image_path in images:
        monitor.process_image(image_path)
