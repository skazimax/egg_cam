from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .types import Detection


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class NestObservation:
    empty_scene_confirmed: bool
    occluded: bool
    reference_similarity: float | None = None


class NestGuard:
    """Reject empty observations when a nest is occluded or the view is unclear."""

    def __init__(
        self,
        zones: list[list[float]],
        reference_dir: Path | None = None,
        min_reference_similarity: float = 0.80,
        min_detection_overlap: float = 0.10,
    ) -> None:
        if not zones:
            raise ValueError("at least one nest zone is required")
        self.zones = [self._validate_zone(zone) for zone in zones]
        self.reference_dir = reference_dir
        self.min_reference_similarity = min_reference_similarity
        self.min_detection_overlap = min_detection_overlap
        self.reference_paths = self._discover_references(reference_dir)
        self._reference_vectors: dict[
            tuple[int, int], list[list[list[float]]]
        ] = {}
        if reference_dir is not None and not self.reference_paths:
            LOGGER.warning(
                "no empty-nest reference images found in %s; "
                "reference-based collection reset is blocked",
                reference_dir,
            )

    @staticmethod
    def _validate_zone(zone: list[float]) -> tuple[float, float, float, float]:
        if len(zone) != 4:
            raise ValueError("nest zone must contain x1, y1, x2, y2")
        x1, y1, x2, y2 = (float(value) for value in zone)
        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
            raise ValueError("nest zone coordinates must be normalized to 0..1")
        return x1, y1, x2, y2

    @staticmethod
    def _discover_references(reference_dir: Path | None) -> list[Path]:
        if reference_dir is None or not reference_dir.is_dir():
            return []
        extensions = {".jpg", ".jpeg", ".png"}
        return sorted(
            path
            for path in reference_dir.iterdir()
            if path.is_file() and path.suffix.lower() in extensions
        )

    def observe(
        self,
        image_path: Path,
        width: int,
        height: int,
        context_detections: list[Detection],
    ) -> NestObservation:
        occluded = any(
            self._overlaps_any_zone(detection, width, height)
            for detection in context_detections
        )
        if occluded:
            return NestObservation(empty_scene_confirmed=False, occluded=True)

        # A configured but unavailable reference set is a fail-closed state.
        if self.reference_dir is not None and not self.reference_paths:
            return NestObservation(empty_scene_confirmed=False, occluded=False)
        if not self.reference_paths:
            return NestObservation(empty_scene_confirmed=True, occluded=False)

        similarity = self._reference_similarity(image_path, width, height)
        return NestObservation(
            empty_scene_confirmed=similarity >= self.min_reference_similarity,
            occluded=False,
            reference_similarity=similarity,
        )

    def _overlaps_any_zone(
        self, detection: Detection, width: int, height: int
    ) -> bool:
        x1, y1, x2, y2 = detection.box_xyxy
        detection_area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        if detection_area == 0:
            return False
        for zx1, zy1, zx2, zy2 in self.zones:
            left = max(x1, zx1 * width)
            top = max(y1, zy1 * height)
            right = min(x2, zx2 * width)
            bottom = min(y2, zy2 * height)
            intersection = max(0.0, right - left) * max(0.0, bottom - top)
            if intersection / detection_area >= self.min_detection_overlap:
                return True
        return False

    def _reference_similarity(
        self, image_path: Path, width: int, height: int
    ) -> float:
        key = (width, height)
        if key not in self._reference_vectors:
            vectors: list[list[list[float]]] = []
            for path in self.reference_paths:
                with Image.open(path) as image:
                    image = image.convert("L").resize((width, height))
                    vectors.append(self._zone_vectors(image))
            self._reference_vectors[key] = vectors

        with Image.open(image_path) as image:
            image = image.convert("L").resize((width, height))
            current = self._zone_vectors(image)

        best = -1.0
        for reference in self._reference_vectors[key]:
            # Every configured nest must look clear in the same reference frame.
            similarity = min(
                self._correlation(first, second)
                for first, second in zip(current, reference)
            )
            best = max(best, similarity)
        return best

    def _zone_vectors(self, image: Image.Image) -> list[list[float]]:
        width, height = image.size
        vectors: list[list[float]] = []
        for x1, y1, x2, y2 in self.zones:
            crop = image.crop(
                (
                    round(x1 * width),
                    round(y1 * height),
                    round(x2 * width),
                    round(y2 * height),
                )
            ).resize((64, 64))
            vectors.append([float(value) for value in crop.tobytes()])
        return vectors

    @staticmethod
    def _correlation(first: list[float], second: list[float]) -> float:
        first_mean = sum(first) / len(first)
        second_mean = sum(second) / len(second)
        numerator = sum(
            (a - first_mean) * (b - second_mean)
            for a, b in zip(first, second)
        )
        first_norm = sum((value - first_mean) ** 2 for value in first)
        second_norm = sum((value - second_mean) ** 2 for value in second)
        denominator = math.sqrt(first_norm * second_norm)
        return numerator / denominator if denominator else 0.0
