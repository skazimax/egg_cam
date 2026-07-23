from __future__ import annotations

import os
import shutil
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from PIL import Image

from .parsing import extract_json_object, qwen_payload_to_detections
from .types import Detection, ModelResult


QWEN_PROMPT = """Analyze this chicken coop image.
Count only clearly visible real chicken eggs. Do not infer hidden eggs.
Do not count feathers, hay, lamps, bowls, reflections, white floor spots,
parts of chickens, or other oval objects.

Return only valid JSON with this exact structure:
{
  "egg_count": 0,
  "eggs": [
    {
      "box_2d": [ymin, xmin, ymax, xmax],
      "confidence": 0.0,
      "visibility": "full"
    }
  ]
}
Coordinates must be normalized from 0 to 1000. visibility is "full" or
"partial". If no egg is clearly visible, return egg_count 0 and eggs []."""


def local_huggingface_snapshot(model_id: str) -> str:
    """Use a completed local snapshot when weights were downloaded resumably."""
    default_home = Path.home() / ".cache" / "huggingface"
    hf_home = Path(os.environ.get("HF_HOME", default_home))
    model_root = hf_home / "hub" / f"models--{model_id.replace('/', '--')}"
    reference = model_root / "refs" / "main"
    if reference.exists():
        snapshot = model_root / "snapshots" / reference.read_text().strip()
        if snapshot.exists():
            return str(snapshot)
    return model_id


def prepare_transformers_remote_code(source: str) -> None:
    """Populate the dynamic-module cache for resumably downloaded snapshots."""
    source_path = Path(source)
    if not source_path.is_dir():
        return
    hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    target = hf_home / "modules" / "transformers_modules" / source_path.name
    target.mkdir(parents=True, exist_ok=True)
    (target / "__init__.py").touch()
    for module in source_path.glob("*.py"):
        shutil.copy2(module, target / module.name)


def resolve_torch_device(requested: str) -> str:
    if requested != "auto":
        return requested
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class ModelAdapter(ABC):
    name: str

    @abstractmethod
    def load(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def predict(self, image_path: Path) -> ModelResult:
        raise NotImplementedError


class QwenMlxAdapter(ModelAdapter):
    name = "qwen_mlx"

    def __init__(
        self,
        model_id: str = "mlx-community/Qwen2.5-VL-3B-Instruct-4bit",
        max_tokens: int = 256,
    ) -> None:
        self.model_id = model_id
        self.max_tokens = max_tokens
        self.model: Any = None
        self.processor: Any = None
        self.config: Any = None

    def load(self) -> None:
        from mlx_vlm import load
        from mlx_vlm.utils import load_config

        self.model, self.processor = load(self.model_id)
        self.config = load_config(self.model_id)

    def predict(self, image_path: Path) -> ModelResult:
        from mlx_vlm import generate
        from mlx_vlm.prompt_utils import apply_chat_template

        image = Image.open(image_path).convert("RGB")
        width, height = image.size
        formatted = apply_chat_template(
            self.processor,
            self.config,
            QWEN_PROMPT,
            num_images=1,
        )
        started = time.perf_counter()
        output = generate(
            self.model,
            self.processor,
            formatted,
            [str(image_path)],
            max_tokens=self.max_tokens,
            temperature=0.0,
            verbose=False,
        )
        latency = time.perf_counter() - started
        text = getattr(output, "text", output)
        text = str(text)
        try:
            payload = extract_json_object(text)
            count, detections = qwen_payload_to_detections(payload, width, height)
            return ModelResult(
                model=self.name,
                image=str(image_path),
                width=width,
                height=height,
                latency_seconds=latency,
                detections=detections,
                reported_count=count,
                raw_output=text,
            )
        except Exception as exc:
            return ModelResult(
                model=self.name,
                image=str(image_path),
                width=width,
                height=height,
                latency_seconds=latency,
                raw_output=text,
                error=f"invalid model response: {exc}",
            )


class YoloWorldAdapter(ModelAdapter):
    name = "yolo_world"

    def __init__(
        self,
        model_id: str = "yolov8s-worldv2.pt",
        classes: list[str] | None = None,
        confidence: float = 0.005,
        image_size: int = 1280,
        tile_grid: int = 1,
        tile_overlap: float = 0.15,
        device: str = "auto",
    ) -> None:
        self.model_id = model_id
        self.classes = classes or ["egg", "white egg", "brown egg"]
        self.confidence = confidence
        self.image_size = image_size
        self.tile_grid = max(1, tile_grid)
        self.tile_overlap = max(0.0, min(0.49, tile_overlap))
        self.device = device
        self.model: Any = None

    def load(self) -> None:
        import torch
        from ultralytics import YOLOWorld

        self.model = YOLOWorld(self.model_id)
        self.model.set_classes(self.classes)
        self.device = resolve_torch_device(self.device)

    def predict(self, image_path: Path) -> ModelResult:
        image = Image.open(image_path).convert("RGB")
        width, height = image.size
        started = time.perf_counter()
        tiles = self._make_tiles(image)
        predictions = self.model.predict(
            source=[tile[0] for tile in tiles],
            imgsz=self.image_size,
            conf=self.confidence,
            device=self.device,
            agnostic_nms=True,
            verbose=False,
        )
        latency = time.perf_counter() - started
        detections: list[Detection] = []
        for result, (_, offset_x, offset_y) in zip(predictions, tiles):
            if result.boxes is not None:
                for box, score, class_id in zip(
                    result.boxes.xyxy.cpu().tolist(),
                    result.boxes.conf.cpu().tolist(),
                    result.boxes.cls.cpu().tolist(),
                ):
                    x1, y1, x2, y2 = box
                    detections.append(
                        Detection(
                            label=result.names[int(class_id)],
                            score=float(score),
                            box_xyxy=[
                                float(x1 + offset_x),
                                float(y1 + offset_y),
                                float(x2 + offset_x),
                                float(y2 + offset_y),
                            ],
                        )
                    )
        detections = self._nms(detections, iou_threshold=0.35)
        return ModelResult(
            model=self.name,
            image=str(image_path),
            width=width,
            height=height,
            latency_seconds=latency,
            detections=detections,
        )

    def _make_tiles(self, image: Image.Image) -> list[tuple[Image.Image, int, int]]:
        if self.tile_grid == 1:
            return [(image, 0, 0)]
        width, height = image.size
        base_width = width / self.tile_grid
        base_height = height / self.tile_grid
        overlap_x = base_width * self.tile_overlap
        overlap_y = base_height * self.tile_overlap
        tiles: list[tuple[Image.Image, int, int]] = []
        for row in range(self.tile_grid):
            for column in range(self.tile_grid):
                left = max(0, round(column * base_width - overlap_x))
                top = max(0, round(row * base_height - overlap_y))
                right = min(width, round((column + 1) * base_width + overlap_x))
                bottom = min(height, round((row + 1) * base_height + overlap_y))
                tiles.append((image.crop((left, top, right, bottom)), left, top))
        return tiles

    @staticmethod
    def _nms(detections: list[Detection], iou_threshold: float) -> list[Detection]:
        kept: list[Detection] = []
        for candidate in sorted(detections, key=lambda item: item.score, reverse=True):
            if all(
                YoloWorldAdapter._iou(candidate.box_xyxy, item.box_xyxy) < iou_threshold
                for item in kept
            ):
                kept.append(candidate)
        return kept

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


class GroundingDinoAdapter(ModelAdapter):
    name = "grounding_dino"

    def __init__(
        self,
        model_id: str = "IDEA-Research/grounding-dino-tiny",
        classes: list[str] | None = None,
        box_threshold: float = 0.15,
        text_threshold: float = 0.15,
        device: str = "cpu",
    ) -> None:
        self.model_id = model_id
        self.classes = classes or ["a chicken egg"]
        self.box_threshold = box_threshold
        self.text_threshold = text_threshold
        self.device = device
        self.processor: Any = None
        self.model: Any = None

    def load(self) -> None:
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

        self.processor = AutoProcessor.from_pretrained(self.model_id)
        self.model = AutoModelForZeroShotObjectDetection.from_pretrained(self.model_id)
        self.model.to(self.device)
        self.model.eval()

    def predict(self, image_path: Path) -> ModelResult:
        import torch

        image = Image.open(image_path).convert("RGB")
        width, height = image.size
        text = ". ".join(self.classes) + "."
        inputs = self.processor(images=image, text=text, return_tensors="pt").to(
            self.device
        )
        started = time.perf_counter()
        with torch.inference_mode():
            outputs = self.model(**inputs)
        processed = self.processor.post_process_grounded_object_detection(
            outputs,
            inputs.input_ids,
            threshold=self.box_threshold,
            text_threshold=self.text_threshold,
            target_sizes=[(height, width)],
        )[0]
        latency = time.perf_counter() - started
        labels = processed.get("text_labels", processed.get("labels", []))
        detections = [
            Detection(
                label=str(label),
                score=float(score),
                box_xyxy=[float(value) for value in box],
            )
            for box, score, label in zip(
                processed["boxes"].cpu().tolist(),
                processed["scores"].cpu().tolist(),
                labels,
            )
        ]
        return ModelResult(
            model=self.name,
            image=str(image_path),
            width=width,
            height=height,
            latency_seconds=latency,
            detections=detections,
        )


class OwlV2Adapter(ModelAdapter):
    name = "owlv2"

    def __init__(
        self,
        model_id: str = "google/owlv2-base-patch16-ensemble",
        classes: list[str] | None = None,
        confidence: float = 0.02,
        device: str = "auto",
    ) -> None:
        self.model_id = model_id
        self.classes = classes or ["a chicken egg", "a white egg", "a brown egg"]
        self.confidence = confidence
        self.device = device
        self.processor: Any = None
        self.model: Any = None

    def load(self) -> None:
        import torch
        from transformers import Owlv2ForObjectDetection, Owlv2Processor

        self.device = resolve_torch_device(self.device)
        source = local_huggingface_snapshot(self.model_id)
        self.processor = Owlv2Processor.from_pretrained(source)
        self.model = Owlv2ForObjectDetection.from_pretrained(source)
        self.model.to(self.device)
        self.model.eval()

    def predict(self, image_path: Path) -> ModelResult:
        import torch

        image = Image.open(image_path).convert("RGB")
        width, height = image.size
        texts = [self.classes]
        inputs = self.processor(text=texts, images=image, return_tensors="pt").to(
            self.device
        )
        started = time.perf_counter()
        with torch.inference_mode():
            outputs = self.model(**inputs)
        processed = self.processor.image_processor.post_process_object_detection(
            outputs=outputs,
            target_sizes=torch.tensor([[height, width]], device=self.device),
            threshold=self.confidence,
        )[0]
        latency = time.perf_counter() - started
        detections = [
            Detection(
                label=self.classes[int(label)],
                score=float(score),
                box_xyxy=[float(value) for value in box],
            )
            for box, score, label in zip(
                processed["boxes"].cpu().tolist(),
                processed["scores"].cpu().tolist(),
                processed["labels"].cpu().tolist(),
            )
        ]
        return ModelResult(
            model=self.name,
            image=str(image_path),
            width=width,
            height=height,
            latency_seconds=latency,
            detections=YoloWorldAdapter._nms(detections, iou_threshold=0.35),
        )


class Moondream2Adapter(ModelAdapter):
    name = "moondream2"

    def __init__(
        self,
        model_id: str = "vikhyatk/moondream2",
        revision: str = "2025-06-21",
        query: str = "chicken egg",
        device: str = "auto",
    ) -> None:
        self.model_id = model_id
        self.revision = revision
        self.query = query
        self.device = device
        self.model: Any = None

    def load(self) -> None:
        import torch
        from transformers import AutoModelForCausalLM

        self.device = resolve_torch_device(self.device)
        source = local_huggingface_snapshot(self.model_id)
        prepare_transformers_remote_code(source)
        self.model = AutoModelForCausalLM.from_pretrained(
            source,
            revision=self.revision,
            trust_remote_code=True,
            device_map={"": self.device},
        )
        self.model.eval()

    def predict(self, image_path: Path) -> ModelResult:
        image = Image.open(image_path).convert("RGB")
        width, height = image.size
        started = time.perf_counter()
        payload = self.model.detect(image, self.query)
        latency = time.perf_counter() - started
        objects = payload.get("objects", [])
        detections = [
            Detection(
                label=self.query,
                score=1.0,
                box_xyxy=[
                    float(item["x_min"]) * width,
                    float(item["y_min"]) * height,
                    float(item["x_max"]) * width,
                    float(item["y_max"]) * height,
                ],
            )
            for item in objects
        ]
        return ModelResult(
            model=self.name,
            image=str(image_path),
            width=width,
            height=height,
            latency_seconds=latency,
            detections=detections,
            raw_output=str(payload),
        )


def build_adapter(name: str, config: dict[str, Any]) -> ModelAdapter:
    adapters = {
        "qwen_mlx": QwenMlxAdapter,
        "yolo_world": YoloWorldAdapter,
        "grounding_dino": GroundingDinoAdapter,
        "owlv2": OwlV2Adapter,
        "moondream2": Moondream2Adapter,
    }
    if name not in adapters:
        available = ", ".join(sorted(adapters))
        raise ValueError(f"unknown model {name!r}; available models: {available}")
    return adapters[name](**config)
