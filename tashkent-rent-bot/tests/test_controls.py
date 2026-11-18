from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock

from rentbot.storage import Store
from rentbot.telegram import BotAPI, RULES_TEXT, handle_update


class ControlTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)
        self.bot = BotAPI("not-a-real-token", 123)
        self.bot.call = AsyncMock(return_value={"message_id": 1})
        self.now = datetime(2026, 1, 12, 12, tzinfo=timezone.utc)
        for tier in ("quiet", "loud"):
            self.store.enqueue(tier, "revision-1", tier, {"text": tier}, self.now)

    def update(self, text, *, chat=123, sender=123, kind="private"):
        return {"message": {"chat": {"id": chat, "type": kind},
                            "from": {"id": sender}, "text": text}}

    async def test_pause_and_resume_buttons_preserve_the_entire_queue(self):
        queued = self.store.due(self.now)
        for label, paused in (("⏸ Пауза", "true"), ("▶️ Возобновить", "false")):
            with self.subTest(button=label):
                await handle_update(self.update(label), self.bot, self.store)
                self.assertEqual(self.store.get_meta("paused"), paused)
                self.assertEqual(self.store.due(self.now), queued)
                self.assertEqual(self.store.counts()["pending"], 2)
                self.assertTrue(self.bot.call.call_args.kwargs["disable_notification"])
        self.assertEqual(self.bot.call.await_count, 2)

    async def test_other_users_and_group_buttons_cannot_control_delivery(self):
        queued = self.store.due(self.now)
        origins = ((999, 999, "private"), (123, 999, "private"),
                   (999, 123, "private"), (123, 123, "group"),
                   (123, 123, "supergroup"))
        for label, initial in (("⏸ Пауза", "false"), ("▶️ Возобновить", "true")):
            for chat, sender, kind in origins:
                with self.subTest(button=label, chat=chat, sender=sender, kind=kind):
                    self.store.set_meta("paused", initial)
                    await handle_update(self.update(label, chat=chat, sender=sender, kind=kind),
                                        self.bot, self.store)
                    self.assertEqual(self.store.get_meta("paused"), initial)
                    self.assertEqual(self.store.due(self.now), queued)
        self.bot.call.assert_not_awaited()

    async def test_status_rules_buttons_and_menu_commands_answer_owner(self):
        self.store.set_meta("paused", "true")
        for text in ("📊 Состояние", "/status"):
            await handle_update(self.update(text), self.bot, self.store)
            answer = self.bot.call.call_args.kwargs["text"]
            self.assertIn("В очереди: 2", answer)
            self.assertIn("пауза", answer)
        for text in ("📋 Правила", "/rules"):
            await handle_update(self.update(text), self.bot, self.store)
            self.assertEqual(self.bot.call.call_args.kwargs["text"], RULES_TEXT)
        for text in ("/menu", "/help", "/start"):
            await handle_update(self.update(text), self.bot, self.store)
            answer = self.bot.call.call_args.kwargs["text"]
            self.assertIn("/status", answer)
            self.assertIn("/pause", answer)
        self.assertEqual(self.bot.call.await_count, 7)
        self.assertEqual(self.store.get_meta("paused"), "true")

    async def test_button_label_must_match_the_whole_message(self):
        for text in ("⏸ Пауза позже", "▶️ Возобновить завтра"):
            await handle_update(self.update(text), self.bot, self.store)
        self.assertIsNone(self.store.get_meta("paused"))
        self.bot.call.assert_not_awaited()

    async def test_keyboard_is_attached_without_changing_notification_mode(self):
        keyboard = {"keyboard": [["📊 Состояние", "📋 Правила"],
                                 ["⏸ Пауза", "▶️ Возобновить"]],
                    "resize_keyboard": True, "is_persistent": True,
                    "one_time_keyboard": False}
        for silent in (True, False):
            with self.subTest(silent=silent):
                await self.bot.message("Объявление", silent=silent)
                call = self.bot.call.call_args
                self.assertEqual(call.args, ("sendMessage",))
                self.assertIs(call.kwargs["disable_notification"], silent)
                for key, expected in keyboard.items():
                    self.assertEqual(call.kwargs["reply_markup"][key], expected)
                self.assertEqual(call.kwargs["chat_id"], 123)
        await self.bot.message("Ответ на команду")
        self.assertTrue(self.bot.call.call_args.kwargs["disable_notification"])
        for key, expected in keyboard.items():
            self.assertEqual(self.bot.call.call_args.kwargs["reply_markup"][key], expected)


if __name__ == "__main__":
    unittest.main()
