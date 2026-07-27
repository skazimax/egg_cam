import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from egg_benchmark.nest import NestGuard
from egg_benchmark.types import Detection, ModelResult


def patterned_image(path: Path, inverted: bool = False) -> None:
    image = Image.new("RGB", (100, 100), "white" if inverted else "black")
    draw = ImageDraw.Draw(image)
    draw.rectangle(
        (50, 0, 99, 99), fill="black" if inverted else "white"
    )
    image.save(path)


class NestGuardTest(unittest.TestCase):
    def test_context_detections_do_not_change_egg_count(self) -> None:
        result = ModelResult(
            model="owlv2",
            image="frame.jpg",
            width=100,
            height=100,
            latency_seconds=1.0,
            context_detections=[Detection("a chicken", 0.8, [0, 0, 50, 50])],
        )

        self.assertEqual(result.count, 0)

    def test_chicken_overlapping_nest_blocks_empty_observation(self) -> None:
        guard = NestGuard(zones=[[0.2, 0.2, 0.6, 0.6]])
        chicken = Detection("a chicken", 0.8, [30, 30, 70, 70])

        observation = guard.observe(Path("unused.jpg"), 100, 100, [chicken])

        self.assertTrue(observation.occluded)
        self.assertFalse(observation.empty_scene_confirmed)

    def test_chicken_outside_nest_does_not_block(self) -> None:
        guard = NestGuard(zones=[[0.2, 0.2, 0.6, 0.6]])
        chicken = Detection("a chicken", 0.8, [70, 70, 95, 95])

        observation = guard.observe(Path("unused.jpg"), 100, 100, [chicken])

        self.assertFalse(observation.occluded)
        self.assertTrue(observation.empty_scene_confirmed)

    def test_reference_must_match_clear_nest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            references = root / "references"
            references.mkdir()
            reference = references / "empty.jpg"
            matching = root / "matching.jpg"
            changed = root / "changed.jpg"
            patterned_image(reference)
            patterned_image(matching)
            patterned_image(changed, inverted=True)
            guard = NestGuard(
                zones=[[0.0, 0.0, 1.0, 1.0]],
                reference_dir=references,
                min_reference_similarity=0.8,
            )

            clear = guard.observe(matching, 100, 100, [])
            unclear = guard.observe(changed, 100, 100, [])

        self.assertTrue(clear.empty_scene_confirmed)
        self.assertGreaterEqual(clear.reference_similarity or 0, 0.8)
        self.assertFalse(unclear.empty_scene_confirmed)

    def test_missing_configured_references_fail_closed(self) -> None:
        guard = NestGuard(
            zones=[[0.0, 0.0, 1.0, 1.0]],
            reference_dir=Path("missing-reference-directory"),
        )

        observation = guard.observe(Path("unused.jpg"), 100, 100, [])

        self.assertFalse(observation.empty_scene_confirmed)


if __name__ == "__main__":
    unittest.main()
