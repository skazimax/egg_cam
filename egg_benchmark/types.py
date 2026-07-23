from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Detection:
    label: str
    score: float
    box_xyxy: list[float]
    visibility: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ModelResult:
    model: str
    image: str
    width: int
    height: int
    latency_seconds: float
    detections: list[Detection] = field(default_factory=list)
    reported_count: int | None = None
    raw_output: str | None = None
    error: str | None = None

    @property
    def count(self) -> int:
        if self.reported_count is not None:
            return self.reported_count
        return len(self.detections)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["count"] = self.count
        return payload

    @property
    def image_name(self) -> str:
        return Path(self.image).name

