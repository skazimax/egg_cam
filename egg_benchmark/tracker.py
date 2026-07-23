from __future__ import annotations

from dataclasses import dataclass

from .types import Detection


@dataclass
class EggTrack:
    track_id: int
    detection: Detection
    hits: int = 1
    misses: int = 0
    counted: bool = False


class EggTracker:
    """Track persistent egg boxes and emit each newly confirmed egg once."""

    def __init__(
        self,
        confirm_frames: int = 2,
        warmup_frames: int = 2,
        max_missed_frames: int = 1,
        iou_threshold: float = 0.20,
        max_center_distance: float = 0.035,
    ) -> None:
        self.confirm_frames = max(1, confirm_frames)
        self.warmup_frames = max(1, warmup_frames)
        self.max_missed_frames = max(0, max_missed_frames)
        self.iou_threshold = iou_threshold
        self.max_center_distance = max_center_distance
        self.frame_index = 0
        self._next_id = 1
        self.tracks: list[EggTrack] = []

    @property
    def has_unconfirmed_candidates(self) -> bool:
        if self.frame_index <= self.warmup_frames:
            return False
        return any(
            not track.counted and track.hits > 0 and track.misses == 0
            for track in self.tracks
        )

    @property
    def needs_warmup(self) -> bool:
        return self.frame_index < self.warmup_frames

    def update(
        self, detections: list[Detection], width: int, height: int
    ) -> list[Detection]:
        self.frame_index += 1
        matched_tracks: set[int] = set()
        matched_detections: set[int] = set()

        candidates: list[tuple[float, int, int]] = []
        for track_index, track in enumerate(self.tracks):
            for detection_index, detection in enumerate(detections):
                score = self._match_score(
                    track.detection.box_xyxy,
                    detection.box_xyxy,
                    width,
                    height,
                )
                if score is not None:
                    candidates.append((score, track_index, detection_index))

        for _, track_index, detection_index in sorted(candidates, reverse=True):
            if track_index in matched_tracks or detection_index in matched_detections:
                continue
            track = self.tracks[track_index]
            track.detection = detections[detection_index]
            track.hits += 1
            track.misses = 0
            matched_tracks.add(track_index)
            matched_detections.add(detection_index)

        for track_index, track in enumerate(self.tracks):
            if track_index not in matched_tracks:
                track.misses += 1
                if not track.counted:
                    track.hits = 0

        self.tracks = [
            track for track in self.tracks if track.misses <= self.max_missed_frames
        ]

        for detection_index, detection in enumerate(detections):
            if detection_index in matched_detections:
                continue
            self.tracks.append(
                EggTrack(track_id=self._next_id, detection=detection)
            )
            self._next_id += 1

        newly_confirmed: list[Detection] = []
        for track in self.tracks:
            if track.counted or track.hits < self.confirm_frames:
                continue
            track.counted = True
            if self.frame_index > self.warmup_frames:
                newly_confirmed.append(track.detection)
        return newly_confirmed

    def _match_score(
        self,
        first: list[float],
        second: list[float],
        width: int,
        height: int,
    ) -> float | None:
        iou = self._iou(first, second)
        if iou >= self.iou_threshold:
            return 2.0 + iou
        first_x = (first[0] + first[2]) / 2 / width
        first_y = (first[1] + first[3]) / 2 / height
        second_x = (second[0] + second[2]) / 2 / width
        second_y = (second[1] + second[3]) / 2 / height
        distance = ((first_x - second_x) ** 2 + (first_y - second_y) ** 2) ** 0.5
        if distance <= self.max_center_distance:
            return 1.0 - distance / self.max_center_distance
        return None

    @staticmethod
    def _iou(first: list[float], second: list[float]) -> float:
        left = max(first[0], second[0])
        top = max(first[1], second[1])
        right = min(first[2], second[2])
        bottom = min(first[3], second[3])
        intersection = max(0.0, right - left) * max(0.0, bottom - top)
        first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
        second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
        union = first_area + second_area - intersection
        return intersection / union if union else 0.0
