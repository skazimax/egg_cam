import argparse
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from egg_benchmark.cli import send_telegram_test


class TelegramTestCommandTest(unittest.TestCase):
    def test_sends_selected_photo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "egg.jpg"
            image.write_bytes(b"test-image")
            telegram = Mock(enabled=True)
            args = argparse.Namespace(
                image=image,
                caption="test caption",
                detect=False,
                config=Path("config.yaml"),
                output=Path("annotated.jpg"),
            )

            with patch(
                "egg_benchmark.cli.TelegramClient.from_environment",
                return_value=telegram,
            ):
                result = send_telegram_test(args)

        self.assertEqual(result, 0)
        telegram.send_photo.assert_called_once_with(image, "test caption")

    def test_requires_telegram_credentials(self) -> None:
        telegram = Mock(enabled=False)
        args = argparse.Namespace(
            image=Path("egg.jpg"),
            caption="test",
            detect=False,
            config=Path("config.yaml"),
            output=Path("annotated.jpg"),
        )

        with patch(
            "egg_benchmark.cli.TelegramClient.from_environment",
            return_value=telegram,
        ):
            result = send_telegram_test(args)

        self.assertEqual(result, 2)
        telegram.send_photo.assert_not_called()

    def test_detects_and_sends_annotated_photo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "egg.jpg"
            image.write_bytes(b"test-image")
            output = root / "annotated.jpg"
            telegram = Mock(enabled=True)
            adapter = Mock()
            adapter.predict.return_value = SimpleNamespace(
                error=None,
                detections=[Mock()],
                count=1,
            )
            args = argparse.Namespace(
                image=image,
                caption="test caption",
                detect=True,
                config=root / "config.yaml",
                output=output,
            )

            with (
                patch(
                    "egg_benchmark.cli.TelegramClient.from_environment",
                    return_value=telegram,
                ),
                patch("egg_benchmark.cli.load_config", return_value={}),
                patch("egg_benchmark.cli.build_adapter", return_value=adapter),
                patch("egg_benchmark.cli.save_annotated") as save_annotated,
            ):
                result = send_telegram_test(args)

        self.assertEqual(result, 0)
        adapter.load.assert_called_once_with()
        save_annotated.assert_called_once_with(
            adapter.predict.return_value,
            output,
            highlighted=adapter.predict.return_value.detections,
            label_mode="none",
            line_width=2,
        )
        telegram.send_photo.assert_called_once_with(
            output,
            "test caption\n🥚 Найдено яиц: 1",
        )


if __name__ == "__main__":
    unittest.main()
