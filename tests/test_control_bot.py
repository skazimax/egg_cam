import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock

from egg_benchmark.control_bot import (
    ControlBot,
    HelperResult,
    parse_admin_user_ids,
)


class ControlBotTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = Mock(return_value=HelperResult(True, "egg-cam active"))
        self.bot = ControlBot("secret", {123}, helper_runner=self.runner)
        self.bot.api = Mock(return_value=True)  # type: ignore[method-assign]

    def message(self, text: str, user_id: int = 123, chat_type: str = "private"):
        return {
            "message": {
                "text": text,
                "from": {"id": user_id},
                "chat": {"id": user_id, "type": chat_type},
            }
        }

    def test_parses_admin_ids(self) -> None:
        self.assertEqual(parse_admin_user_ids("123, 456"), {123, 456})
        with self.assertRaises(ValueError):
            parse_admin_user_ids("username")

    def test_status_runs_only_allowlisted_helper_action(self) -> None:
        self.bot.handle_update(self.message("/status"))
        self.runner.assert_called_once_with("status")
        sent = self.bot.api.call_args_list[-1].args
        self.assertEqual(sent[0], "sendMessage")
        self.assertIn("egg-cam active", sent[1]["text"])

    def test_bot_suffix_and_arguments_are_ignored(self) -> None:
        self.bot.handle_update(self.message("/egg_off@my_bot now"))
        self.runner.assert_called_once_with("egg-off")

    def test_unknown_command_never_runs_helper(self) -> None:
        self.bot.handle_update(self.message("/shell rm"))
        self.runner.assert_not_called()

    def test_rejects_unknown_user(self) -> None:
        self.bot.handle_update(self.message("/status", user_id=999))
        self.runner.assert_not_called()
        self.assertIn("Нет доступа", self.bot.api.call_args.args[1]["text"])

    def test_rejects_group_commands(self) -> None:
        self.bot.handle_update(self.message("/status", chat_type="group"))
        self.runner.assert_not_called()

    def test_callback_is_acknowledged_and_executed(self) -> None:
        update = {
            "callback_query": {
                "id": "callback-1",
                "data": "/water_status",
                "from": {"id": 123},
                "message": {"chat": {"id": 123, "type": "private"}},
            }
        }
        self.bot.handle_update(update)
        self.runner.assert_called_once_with("water-status")
        self.assertEqual(self.bot.api.call_args_list[0].args[0], "answerCallbackQuery")

    def test_poll_persists_next_update_offset_before_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            offset_file = Path(directory) / "offset"
            bot = ControlBot(
                "secret", {123}, helper_runner=self.runner, offset_file=offset_file
            )
            bot.api = Mock(  # type: ignore[method-assign]
                side_effect=[
                    [{"update_id": 41, **self.message("/status")}],
                    True,
                ]
            )
            bot.poll_once()
            self.assertEqual(offset_file.read_text(encoding="utf-8"), "42")

            restarted = ControlBot(
                "secret", {123}, helper_runner=self.runner, offset_file=offset_file
            )
            self.assertEqual(restarted.offset, 42)


if __name__ == "__main__":
    unittest.main()
