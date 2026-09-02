from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests


LOGGER = logging.getLogger(__name__)


COMMANDS: dict[str, tuple[str | None, str]] = {
    "/status": ("status", "Статус"),
    "/egg_on": ("egg-on", "Яйца: включение"),
    "/egg_off": ("egg-off", "Яйца: выключение"),
    "/egg_restart": ("egg-restart", "Яйца: перезапуск"),
    "/water_status": ("water-status", "Вода: статус"),
    "/water_daily": ("water-daily", "Вода: дневной отчёт"),
    "/water_weekly": ("water-weekly", "Вода: недельный отчёт"),
    "/network_status": ("network-status", "Сеть"),
    "/sstp_restart": ("sstp-restart", "SSTP: перезапуск"),
    "/adguard_restart": ("adguard-restart", "AdGuard: перезапуск"),
    "/help": (None, "Справка"),
    "/start": (None, "Справка"),
}


HELP_TEXT = """Управление сервером egg-cam

/status — состояние всех компонентов
/egg_on — включить мониторинг яиц и автозапуск
/egg_off — остановить мониторинг яиц и отключить автозапуск
/egg_restart — перезапустить мониторинг яиц
/water_status — состояние отчётов по воде
/water_daily — отправить дневной отчёт сейчас
/water_weekly — отправить недельный отчёт сейчас
/network_status — состояние AdGuard, SSTP и маршрута до камеры
/sstp_restart — переподключить SSTP
/adguard_restart — перезапустить AdGuard
"""


def parse_admin_user_ids(value: str | None) -> set[int]:
    if not value:
        return set()
    try:
        return {int(item.strip()) for item in value.split(",") if item.strip()}
    except ValueError as exc:
        raise ValueError("TELEGRAM_ADMIN_USER_IDS must contain numeric IDs") from exc


def command_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "Общий статус", "callback_data": "/status"},
                {"text": "Статус сети", "callback_data": "/network_status"},
            ],
            [
                {"text": "Включить яйца", "callback_data": "/egg_on"},
                {"text": "Выключить яйца", "callback_data": "/egg_off"},
            ],
            [
                {"text": "Статус воды", "callback_data": "/water_status"},
                {"text": "Дневной отчёт", "callback_data": "/water_daily"},
            ],
        ]
    }


@dataclass
class HelperResult:
    ok: bool
    output: str


def run_helper(action: str, timeout: int = 180) -> HelperResult:
    helper = os.environ.get(
        "EGG_CAM_CONTROL_HELPER", "/usr/local/sbin/egg-cam-control"
    )
    try:
        result = subprocess.run(
            ["sudo", helper, action],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return HelperResult(False, f"Ошибка запуска helper: {type(exc).__name__}")
    output = (result.stdout or result.stderr or "Нет вывода").strip()
    return HelperResult(result.returncode == 0, output[:3500])


class ControlBot:
    def __init__(
        self,
        token: str,
        admin_user_ids: set[int],
        helper_runner: Callable[[str], HelperResult] = run_helper,
        offset_file: Path | None = None,
    ) -> None:
        self.token = token
        self.admin_user_ids = admin_user_ids
        self.helper_runner = helper_runner
        self.offset_file = offset_file
        self.offset = self._load_offset()

    def _load_offset(self) -> int | None:
        if self.offset_file is None or not self.offset_file.exists():
            return None
        try:
            return int(self.offset_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            LOGGER.warning("invalid Telegram offset file; starting without offset")
            return None

    def _save_offset(self) -> None:
        if self.offset_file is None or self.offset is None:
            return
        self.offset_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.offset_file.with_suffix(".tmp")
        temporary.write_text(str(self.offset), encoding="utf-8")
        temporary.replace(self.offset_file)

    def api(self, method: str, payload: dict[str, Any], timeout: int = 40) -> Any:
        response = requests.post(
            f"https://api.telegram.org/bot{self.token}/{method}",
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        body = response.json()
        if not body.get("ok"):
            raise RuntimeError(f"Telegram API returned ok=false for {method}")
        return body.get("result")

    def send(self, chat_id: int, text: str, *, keyboard: bool = False) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if keyboard:
            payload["reply_markup"] = command_keyboard()
        self.api("sendMessage", payload)

    def handle_update(self, update: dict[str, Any]) -> None:
        callback = update.get("callback_query")
        if callback:
            sender = callback.get("from", {})
            message = callback.get("message", {})
            chat = message.get("chat", {})
            command = str(callback.get("data", ""))
            callback_id = callback.get("id")
            if callback_id:
                self.api("answerCallbackQuery", {"callback_query_id": callback_id})
        else:
            message = update.get("message", {})
            sender = message.get("from", {})
            chat = message.get("chat", {})
            text = str(message.get("text", "")).strip()
            command = text.split(maxsplit=1)[0].split("@", maxsplit=1)[0]

        user_id = sender.get("id")
        chat_id = chat.get("id")
        if not isinstance(user_id, int) or not isinstance(chat_id, int):
            return
        if user_id not in self.admin_user_ids:
            LOGGER.warning("rejected Telegram command from user_id=%s", user_id)
            self.send(chat_id, "Нет доступа.")
            return
        if chat.get("type") != "private":
            self.send(chat_id, "Команды управления принимаются только в личном чате.")
            return
        if command not in COMMANDS:
            self.send(chat_id, "Неизвестная команда.\n\n" + HELP_TEXT, keyboard=True)
            return

        action, label = COMMANDS[command]
        if action is None:
            self.send(chat_id, HELP_TEXT, keyboard=True)
            return

        if action not in {"status", "water-status", "network-status"}:
            self.send(chat_id, f"⏳ {label}…")
        result = self.helper_runner(action)
        icon = "✅" if result.ok else "❌"
        self.send(chat_id, f"{icon} {label}\n\n{result.output}", keyboard=True)

    def poll_once(self) -> None:
        payload: dict[str, Any] = {
            "timeout": 30,
            "allowed_updates": ["message", "callback_query"],
        }
        if self.offset is not None:
            payload["offset"] = self.offset
        updates = self.api("getUpdates", payload, timeout=40) or []
        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                self.offset = update_id + 1
                # Persist before executing the action. This gives commands
                # at-most-once semantics if Telegram becomes unavailable while
                # the result is being sent back to the administrator.
                self._save_offset()
            try:
                self.handle_update(update)
            except Exception as exc:  # keep polling after one malformed update
                LOGGER.error("failed to handle Telegram update (%s)", type(exc).__name__)

    def run_forever(self) -> None:
        LOGGER.info("control bot started for %d admin(s)", len(self.admin_user_ids))
        while True:
            try:
                self.poll_once()
            except requests.RequestException as exc:
                LOGGER.warning("Telegram polling failed (%s)", type(exc).__name__)
                time.sleep(5)
            except Exception as exc:
                LOGGER.error("control bot polling error (%s)", type(exc).__name__)
                time.sleep(5)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")
    try:
        admin_user_ids = parse_admin_user_ids(
            os.environ.get("TELEGRAM_ADMIN_USER_IDS")
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    if not admin_user_ids:
        raise SystemExit("TELEGRAM_ADMIN_USER_IDS is required")
    offset_file = Path(
        os.environ.get(
            "TELEGRAM_UPDATE_OFFSET_FILE",
            "runtime/control-bot/update_offset",
        )
    )
    ControlBot(token, admin_user_ids, offset_file=offset_file).run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
