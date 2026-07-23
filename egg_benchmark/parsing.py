from __future__ import annotations

import json
import re
from typing import Any

from .types import Detection


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object from a possibly fenced model response."""
    cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip(), flags=re.I)
    try:
        value = json.loads(cleaned)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    if start < 0:
        raise ValueError("model response does not contain a JSON object")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
        elif not in_string and char == "{":
            depth += 1
        elif not in_string and char == "}":
            depth -= 1
            if depth == 0:
                value = json.loads(cleaned[start : index + 1])
                if not isinstance(value, dict):
                    raise ValueError("model JSON response is not an object")
                return value
    raise ValueError("unterminated JSON object in model response")


def qwen_payload_to_detections(
    payload: dict[str, Any], width: int, height: int
) -> tuple[int, list[Detection]]:
    items = payload.get("eggs") or []
    detections: list[Detection] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        box = item.get("box_2d") or item.get("box")
        if not isinstance(box, list) or len(box) != 4:
            continue
        # Qwen prompt requests [ymin, xmin, ymax, xmax], normalized to 0..1000.
        ymin, xmin, ymax, xmax = (float(value) for value in box)
        if max(abs(value) for value in (ymin, xmin, ymax, xmax)) <= 1.0:
            scale = 1.0
        else:
            scale = 1000.0
        xyxy = [
            max(0.0, min(width, xmin / scale * width)),
            max(0.0, min(height, ymin / scale * height)),
            max(0.0, min(width, xmax / scale * width)),
            max(0.0, min(height, ymax / scale * height)),
        ]
        confidence = item.get("confidence", 0.5)
        try:
            score = float(confidence)
        except (TypeError, ValueError):
            score = {"low": 0.3, "medium": 0.6, "high": 0.9}.get(
                str(confidence).lower(), 0.5
            )
        detections.append(
            Detection(
                label="chicken egg",
                score=max(0.0, min(1.0, score)),
                box_xyxy=xyxy,
                visibility=item.get("visibility"),
            )
        )

    reported = payload.get("egg_count", payload.get("count", len(detections)))
    try:
        count = int(reported)
    except (TypeError, ValueError):
        count = len(detections)
    return count, detections

