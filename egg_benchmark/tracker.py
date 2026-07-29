from __future__ import annotations

from .types import Detection


class EggTracker:
    """Confirm growth by stable egg counts, without matching egg positions."""

    def __init__(
        self,
        confirm_frames: int = 2,
        warmup_frames: int = 2,
        session_peak: int | None = None,
    ) -> None:
        self.confirm_frames = max(1, confirm_frames)
        self.warmup_frames = max(1, warmup_frames)
        self.session_peak = max(0, session_peak or 0)
        # A restored peak is already the baseline. A fresh process first learns
        # the eggs that were present before monitoring started.
        self.frame_index = self.warmup_frames if session_peak is not None else 0
        self._warmup_peak = self.session_peak
        self._level_hits: dict[int, int] = {}

    @property
    def has_unconfirmed_candidates(self) -> bool:
        return any(hits > 0 for hits in self._level_hits.values())

    @property
    def needs_warmup(self) -> bool:
        return self.frame_index < self.warmup_frames

    def update(
        self,
        detections: list[Detection],
        width: int,
        height: int,
        is_regular_frame: bool = True,
    ) -> list[Detection]:
        del width, height, is_regular_frame
        self.frame_index += 1
        visible_count = len(detections)

        if self.frame_index <= self.warmup_frames:
            self._warmup_peak = max(self._warmup_peak, visible_count)
            if self.frame_index == self.warmup_frames:
                self.session_peak = max(self.session_peak, self._warmup_peak)
            return []

        highest_level = max(
            [self.session_peak, visible_count, *self._level_hits.keys()]
        )
        for level in range(self.session_peak + 1, highest_level + 1):
            if visible_count >= level:
                self._level_hits[level] = self._level_hits.get(level, 0) + 1
            else:
                self._level_hits.pop(level, None)

        confirmed_peak = self.session_peak
        for level in range(self.session_peak + 1, highest_level + 1):
            if self._level_hits.get(level, 0) < self.confirm_frames:
                break
            confirmed_peak = level

        growth = confirmed_peak - self.session_peak
        if growth <= 0:
            return []

        self.session_peak = confirmed_peak
        self._level_hits = {
            level: hits
            for level, hits in self._level_hits.items()
            if level > self.session_peak
        }
        # The boxes are used only for the notification annotation. Identity is
        # deliberately not carried from one frame to the next.
        return sorted(detections, key=lambda detection: detection.score, reverse=True)[
            :growth
        ]

    def reset_session(self) -> None:
        self.session_peak = 0
        self.frame_index = self.warmup_frames
        self._warmup_peak = 0
        self._level_hits = {}
