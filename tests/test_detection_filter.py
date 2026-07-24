import unittest

from egg_benchmark.models import filter_detections_by_area
from egg_benchmark.types import Detection


class DetectionAreaFilterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.small = Detection("egg", 0.9, [0, 0, 10, 10])
        self.large = Detection("egg", 0.9, [0, 0, 50, 50])

    def test_removes_box_above_configured_frame_ratio(self) -> None:
        filtered = filter_detections_by_area(
            [self.small, self.large],
            width=100,
            height=100,
            max_box_area_ratio=0.02,
        )

        self.assertEqual(filtered, [self.small])

    def test_keeps_box_at_exact_limit(self) -> None:
        filtered = filter_detections_by_area(
            [self.small],
            width=100,
            height=100,
            max_box_area_ratio=0.01,
        )

        self.assertEqual(filtered, [self.small])

    def test_none_or_zero_disables_filter(self) -> None:
        detections = [self.small, self.large]

        self.assertIs(
            filter_detections_by_area(detections, 100, 100, None), detections
        )
        self.assertIs(
            filter_detections_by_area(detections, 100, 100, 0), detections
        )


if __name__ == "__main__":
    unittest.main()
