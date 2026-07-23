import unittest

from egg_benchmark.parsing import extract_json_object, qwen_payload_to_detections


class ParsingTest(unittest.TestCase):
    def test_extracts_fenced_json(self) -> None:
        value = extract_json_object('```json\n{"egg_count": 1, "eggs": []}\n```')
        self.assertEqual(value["egg_count"], 1)

    def test_converts_normalized_yxyx_box(self) -> None:
        payload = {
            "egg_count": 1,
            "eggs": [
                {
                    "box_2d": [100, 200, 300, 400],
                    "confidence": 0.9,
                    "visibility": "full",
                }
            ],
        }
        count, detections = qwen_payload_to_detections(payload, 2000, 1000)
        self.assertEqual(count, 1)
        self.assertEqual(detections[0].box_xyxy, [400.0, 100.0, 800.0, 300.0])


if __name__ == "__main__":
    unittest.main()

