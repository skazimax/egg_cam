from __future__ import annotations

import logging
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .models import ModelAdapter
from .nest import NestGuard
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
        nest_guard: NestGuard | None = None,
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
        self.nest_guard = nest_guard
        self.last_empty_candidate = False
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
        observation = (
            self.nest_guard.observe(
                image_path,
                result.width,
                result.height,
                result.context_detections,
            )
            if self.nest_guard is not None
            else None
        )
        new_eggs = self.tracker.update(
            result.detections,
            result.width,
            result.height,
            is_regular_frame=is_regular_frame,
        )
        self.last_empty_candidate = bool(
            self.tracker.session_peak > 0
            and result.count == 0
            and observation is not None
            and not observation.occluded
            and observation.empty_scene_confirmed
        )
        self._persist_tracker_state()
        LOGGER.info(
            "frame=%s visible=%d session_peak=%d new=%d hens=%d "
            "nest_state=%s nest_similarity=%s empty_candidate=%s latency=%.2fs",
            image_path.name,
            result.count,
            self.tracker.session_peak,
            len(new_eggs),
            len(result.context_detections),
            "occluded"
            if observation is not None and observation.occluded
            else "clear"
            if observation is not None and observation.empty_scene_confirmed
            else "unclear",
            "-"
            if observation is None or observation.reference_similarity is None
            else f"{observation.reference_similarity:.3f}",
            self.last_empty_candidate,
            result.latency_seconds,
        )
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

    def confirm_empty_collection(self, image_path: Path) -> None:
        previous_peak = self.tracker.session_peak
        caption = "🥚 Яйца собраны — обнуляю сессию."
        if self.dry_run:
            LOGGER.info("dry-run collection photo: %s; %s", image_path, caption)
        else:
            # Reset only after Telegram accepts the notification. On a network
            # failure the empty sequence will be retried without losing state.
            self.telegram.send_photo(image_path, caption)
        self.tracker.reset_session()
        self.last_empty_candidate = False
        self._persist_tracker_state()
        LOGGER.info(
            "empty nest confirmed; inventory session reset from peak=%d",
            previous_peak,
        )

    def _persist_tracker_state(self) -> None:
        self.store.set_metadata(
            "inventory_session_peak", str(self.tracker.session_peak)
        )

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
    egg_confirmation_frames: int = 3,
    egg_confirmation_interval_seconds: float = 5.0,
    empty_confirmation_frames: int = 3,
    empty_confirmation_interval_seconds: float = 5.0,
    empty_final_delay_seconds: float = 60.0,
) -> None:
    egg_confirmation_frames = max(1, egg_confirmation_frames)
    empty_confirmation_frames = max(1, empty_confirmation_frames)

    def remaining_capacity() -> int | None:
        if max_frames is None:
            return None
        return max(0, max_frames - processed)

    def capture_batch(count: int, interval: float) -> list[Path]:
        capacity = remaining_capacity()
        if capacity is not None:
            count = min(count, capacity)
        paths: list[Path] = []
        next_capture = time.monotonic()
        for _ in range(count):
            delay = next_capture - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            paths.append(capture_rtsp_frame(rtsp_url, frames_dir))
            next_capture += max(0.0, interval)
        return paths

    processed = 0
    while max_frames is None or processed < max_frames:
        started = time.monotonic()
        try:
            image_path = capture_rtsp_frame(rtsp_url, frames_dir)
            new_eggs = monitor.process_image(image_path)
            processed += 1
            needs_egg_confirmation = new_eggs == 0 and (
                monitor.tracker.needs_warmup
                or monitor.tracker.has_unconfirmed_candidates
            )
            if needs_egg_confirmation:
                LOGGER.info(
                    "egg candidate: capturing %d confirmation frames at %.1fs interval",
                    egg_confirmation_frames,
                    egg_confirmation_interval_seconds,
                )
                for confirmation_path in capture_batch(
                    egg_confirmation_frames,
                    egg_confirmation_interval_seconds,
                ):
                    monitor.process_image(
                        confirmation_path, is_regular_frame=False
                    )
                    processed += 1
            elif monitor.last_empty_candidate:
                LOGGER.info(
                    "empty candidate: capturing %d confirmation frames at %.1fs interval",
                    empty_confirmation_frames,
                    empty_confirmation_interval_seconds,
                )
                empty_confirmed = True
                confirmation_paths = capture_batch(
                    empty_confirmation_frames,
                    empty_confirmation_interval_seconds,
                )
                if len(confirmation_paths) < empty_confirmation_frames:
                    empty_confirmed = False
                for confirmation_path in confirmation_paths:
                    monitor.process_image(
                        confirmation_path, is_regular_frame=False
                    )
                    processed += 1
                    if not monitor.last_empty_candidate:
                        empty_confirmed = False
                if empty_confirmed and (
                    max_frames is None or processed < max_frames
                ):
                    LOGGER.info(
                        "empty burst confirmed; waiting %.1fs for final check",
                        empty_final_delay_seconds,
                    )
                    time.sleep(max(0.0, empty_final_delay_seconds))
                    final_path = capture_rtsp_frame(rtsp_url, frames_dir)
                    monitor.process_image(final_path, is_regular_frame=False)
                    processed += 1
                    if monitor.last_empty_candidate:
                        monitor.confirm_empty_collection(final_path)
        except Exception:
            LOGGER.exception("monitoring iteration failed")
        remaining = interval_seconds - (time.monotonic() - started)
        if remaining > 0 and (max_frames is None or processed < max_frames):
            time.sleep(remaining)


def replay_images(monitor: EggMonitor, images: Iterable[Path]) -> None:
    for image_path in images:
        monitor.process_image(image_path)
