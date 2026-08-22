from __future__ import annotations

import os
from pathlib import Path

import requests


class TelegramClient:
    def __init__(self, token: str | None, chat_id: str | None) -> None:
        self.token = token
        self.chat_id = chat_id

    @classmethod
    def from_environment(cls) -> "TelegramClient":
        return cls(
            token=os.environ.get("TELEGRAM_BOT_TOKEN"),
            chat_id=os.environ.get("TELEGRAM_CHAT_ID"),
        )

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send_photo(self, image_path: Path, caption: str) -> None:
        self._require_credentials()
        try:
            with image_path.open("rb") as image:
                response = requests.post(
                    f"https://api.telegram.org/bot{self.token}/sendPhoto",
                    data={"chat_id": self.chat_id, "caption": caption},
                    files={"photo": (image_path.name, image, "image/jpeg")},
                    timeout=60,
                )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Telegram photo request failed ({type(exc).__name__})"
            ) from None

    def send_message(self, text: str) -> None:
        self._require_credentials()
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": text},
                timeout=30,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Telegram message request failed ({type(exc).__name__})"
            ) from None

    def _require_credentials(self) -> None:
        if not self.enabled:
            raise RuntimeError(
                "set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID or use --dry-run"
            )
