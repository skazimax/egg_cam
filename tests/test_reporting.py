import tempfile
import unittest
from pathlib import Path

from PIL import Image

from egg_benchmark.reporting import save_annotated
from egg_benchmark.types import Detection, ModelResult


class AnnotationTest(unittest.TestCase):
    def test_none_mode_draws_only_thin_box(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            destination = Path(directory) / "annotated.png"
            Image.new("RGB", (100, 100), "white").save(source)
            detection = Detection("a chicken egg", 0.91, [30, 30, 50, 55])
            result = ModelResult(
                model="owlv2",
                image=str(source),
                width=100,
                height=100,
                latency_seconds=0,
                detections=[detection],
            )

            save_annotated(
                result,
                destination,
                highlighted=[detection],
                label_mode="none",
                line_width=1,
            )

            with Image.open(destination) as image:
                self.assertEqual(image.getpixel((30, 30)), (255, 59, 48))
                self.assertEqual(image.getpixel((31, 31)), (255, 255, 255))
                self.assertEqual(image.getpixel((30, 20)), (255, 255, 255))

    def test_rejects_unknown_label_mode(self) -> None:
        result = ModelResult("owlv2", "unused.jpg", 1, 1, 0)
        with self.assertRaises(ValueError):
            save_annotated(result, Path("unused.jpg"), label_mode="verbose")


if __name__ == "__main__":
    unittest.main()
