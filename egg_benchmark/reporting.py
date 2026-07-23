from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw

from .types import Detection, ModelResult


COLORS = {
    "qwen_mlx": "#00B7FF",
    "yolo_world": "#FF3B30",
    "grounding_dino": "#34C759",
}


def save_annotated(
    result: ModelResult,
    destination: Path,
    highlighted: list[Detection] | None = None,
) -> None:
    image = Image.open(result.image).convert("RGB")
    draw = ImageDraw.Draw(image)
    default_color = COLORS.get(result.model, "#FFD60A")
    highlighted_ids = {id(detection) for detection in highlighted or []}
    line_width = max(3, round(min(image.size) / 350))
    for index, detection in enumerate(result.detections, start=1):
        is_new = id(detection) in highlighted_ids
        color = "#FF3B30" if is_new else default_color
        box = tuple(detection.box_xyxy)
        draw.rectangle(box, outline=color, width=line_width)
        prefix = "NEW " if is_new else ""
        text = f"{prefix}{index}: {detection.label} {detection.score:.2f}"
        left, top, _, _ = draw.textbbox((0, 0), text)
        text_width = draw.textbbox((0, 0), text)[2] - left
        text_height = draw.textbbox((0, 0), text)[3] - top
        x1, y1, _, _ = box
        label_y = max(0, y1 - text_height - 6)
        draw.rectangle(
            (x1, label_y, x1 + text_width + 8, label_y + text_height + 6),
            fill=color,
        )
        draw.text((x1 + 4, label_y + 3), text, fill="black")
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, quality=92)


def write_reports(
    results: list[ModelResult],
    output_dir: Path,
    ground_truth: dict[str, int] | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = [result.as_dict() for result in results]
    (output_dir / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    with (output_dir / "summary.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "image",
                "model",
                "expected_count",
                "count",
                "absolute_error",
                "latency_seconds",
                "error",
            ],
        )
        writer.writeheader()
        for result in results:
            expected = (ground_truth or {}).get(result.image_name)
            writer.writerow(
                {
                    "image": result.image_name,
                    "model": result.model,
                    "expected_count": "" if expected is None else expected,
                    "count": result.count,
                    "absolute_error": ""
                    if expected is None
                    else abs(result.count - expected),
                    "latency_seconds": f"{result.latency_seconds:.3f}",
                    "error": result.error or "",
                }
            )

    lines = [
        "# Egg detection benchmark",
        "",
        "| Image | Model | Expected | Found | Time, s | Error |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for result in results:
        expected = (ground_truth or {}).get(result.image_name)
        lines.append(
            f"| {result.image_name} | {result.model} | "
            f"{'' if expected is None else expected} | {result.count} | "
            f"{result.latency_seconds:.2f} | {result.error or ''} |"
        )
    scored: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for result in results:
        expected = (ground_truth or {}).get(result.image_name)
        if expected is not None and not result.error:
            scored[result.model].append((expected, result.count))
    if scored:
        lines.extend(
            [
                "",
                "## Metrics",
                "",
                "| Model | Exact count accuracy | Mean absolute error |",
                "|---|---:|---:|",
            ]
        )
        for model, pairs in sorted(scored.items()):
            exact = sum(expected == found for expected, found in pairs) / len(pairs)
            mae = sum(abs(expected - found) for expected, found in pairs) / len(pairs)
            lines.append(f"| {model} | {exact:.1%} | {mae:.3f} |")
    lines.append("")
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
