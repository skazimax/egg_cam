import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from egg_benchmark.telegram import TelegramClient


class TelegramErrorSanitizationTest(unittest.TestCase):
    def test_message_error_does_not_expose_bot_token_or_url(self) -> None:
        client = TelegramClient("secret-token", "chat")
        source_error = requests.ConnectionError(
            "failed https://api.telegram.org/botsecret-token/sendMessage"
        )
        with patch("egg_benchmark.telegram.requests.post", side_effect=source_error):
            with self.assertRaisesRegex(
                RuntimeError, "Telegram message request failed"
            ) as raised:
                client.send_message("test")

        self.assertNotIn("secret-token", str(raised.exception))
        self.assertNotIn("api.telegram.org", str(raised.exception))

    def test_photo_error_does_not_expose_bot_token_or_url(self) -> None:
        client = TelegramClient("secret-token", "chat")
        source_error = requests.ConnectionError(
            "failed https://api.telegram.org/botsecret-token/sendPhoto"
        )
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "frame.jpg"
            image.write_bytes(b"frame")
            with patch(
                "egg_benchmark.telegram.requests.post", side_effect=source_error
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "Telegram photo request failed"
                ) as raised:
                    client.send_photo(image, "test")

        self.assertNotIn("secret-token", str(raised.exception))
        self.assertNotIn("api.telegram.org", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
