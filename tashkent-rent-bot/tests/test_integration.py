import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from rentbot.config import Settings
from rentbot.http import APIError
from rentbot.pipeline import Pipeline, SourcePost, group_messages
from rentbot.service import Service, single_instance
from rentbot.storage import Store
from rentbot.telegram import BotAPI, handle_update


NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)  # 17:00 Tashkent
TEXT = ("Сдаётся квартира на длительный срок. Новостройка. Дом сдан 2025-04-01. "
        "2 комнаты, 45 м². Цена 780 USD в месяц. Никто не жил.")


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


class Router:
    async def enrich(self, listing):
        listing.walking_minutes = 18


def message(number, text=TEXT, group=None):
    return SimpleNamespace(id=number, message=text, grouped_id=group, photo=None,
                           document=None, geo=None, action=None, date=NOW - timedelta(hours=1))


class Reader:
    def __init__(self, *messages):
        self.messages = {m.id: m for m in messages}

    async def get_entity(self, channel):
        return channel

    async def get_messages(self, entity, *, limit=None, ids=None):
        if ids is not None:
            return [self.messages.get(i) for i in ids]
        return sorted(self.messages.values(), key=lambda m: m.id, reverse=True)[:limit]

    async def iter_messages(self, entity, *, min_id, reverse, limit):
        messages = sorted((m for m in self.messages.values() if m.id > min_id),
                          key=lambda m: m.id, reverse=not reverse)
        for item in messages[:limit]:
            yield item


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.settings = Settings(1, "", "", 123)
        self.pipeline = Pipeline(self.settings, self.store, Router())

    def tearDown(self):
        self.store.close()

    async def test_quiet_to_loud_replaces_queue_and_repost_is_suppressed(self):
        first = SourcePost([1], TEXT.replace("780", "850"))
        quiet = await self.pipeline.evaluate(first, NOW)
        self.assertEqual(quiet["tier"], "quiet")
        loud = await self.pipeline.evaluate(SourcePost([1], TEXT), NOW)
        self.assertEqual(loud["key"], quiet["key"])
        self.assertEqual(loud["tier"], "loud")
        self.assertEqual(len(self.store.due(NOW)), 1)
        self.store.mark_sent(loud["key"], loud["revision"])
        await self.pipeline.evaluate(SourcePost([1], TEXT), NOW)
        self.assertEqual(self.store.due(NOW), [])

    async def test_exact_cross_post_duplicate_has_one_delivery(self):
        first = await self.pipeline.evaluate(SourcePost([1], TEXT, media_ids=["photo:5"]), NOW)
        second = await self.pipeline.evaluate(SourcePost([50], TEXT, media_ids=["photo:5"]), NOW)
        self.assertEqual(first["key"], second["key"])
        self.assertEqual(len(self.store.due(NOW)), 1)

    async def test_rejected_edit_removes_pending(self):
        first = await self.pipeline.evaluate(SourcePost([1], TEXT), NOW)
        second = await self.pipeline.evaluate(SourcePost([1], TEXT.replace("45 м²", "39 м²")), NOW)
        self.assertEqual(first["key"], second["key"])
        self.assertEqual(second["tier"], "reject")
        self.assertEqual(self.store.due(NOW), [])

    async def test_no_router_data_means_no_loud_notification(self):
        self.pipeline.router = SimpleNamespace(enrich=AsyncMock())
        result = await self.pipeline.evaluate(SourcePost([1], TEXT), NOW)
        self.assertEqual(result["tier"], "quiet")
        self.assertIn("не подтверждено", result["payload"]["summary"])

    def test_album_caption_and_media_remain_together(self):
        first, second = message(1, "", 77), message(2, TEXT, 77)
        first.photo, second.photo = SimpleNamespace(id=10), SimpleNamespace(id=11)
        grouped = group_messages([second, first])
        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped[0].message_ids, [1, 2])
        self.assertEqual(grouped[0].text, TEXT)
        self.assertEqual(len(grouped[0].media_ids), 2)


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.settings = Settings(1, "", "", 123)
        self.reader = Reader(message(1))
        self.bot = SimpleNamespace(chat_id=123, message=AsyncMock(), forward=AsyncMock(return_value=True))
        self.service = Service(self.settings, self.reader, self.bot, self.store)
        self.service.entity = "channel"
        self.service.pipeline.router = Router()
        self.time_patch = patch("rentbot.service.datetime", Clock)
        self.pipeline_patch = patch("rentbot.pipeline.datetime", Clock)
        self.time_patch.start()
        self.pipeline_patch.start()

    def tearDown(self):
        self.time_patch.stop()
        self.pipeline_patch.stop()
        self.store.close()

    async def queued(self, text=TEXT):
        self.reader.messages[1].message = text
        await self.service.pipeline.evaluate(SourcePost([1], text), NOW)
        return self.store.due(NOW)[0]

    async def test_loud_summary_once_and_original_forwarded(self):
        item = await self.queued()
        await self.service.deliver_one(item)
        self.bot.message.assert_awaited_once()
        self.assertFalse(self.bot.message.call_args.kwargs["silent"])
        self.bot.forward.assert_awaited_once_with("Apartament_999", [1])
        self.assertEqual(self.store.counts()["sent"], 1)

    async def test_forward_failure_retry_does_not_resend_summary(self):
        item = await self.queued()
        self.bot.forward.side_effect = [APIError("Telegram", 429, 5), True]
        with self.assertRaises(APIError):
            await self.service.deliver_one(item)
        await self.service.deliver_one(item)
        self.bot.message.assert_awaited_once()
        self.assertEqual(self.store.counts()["sent"], 1)

    async def test_no_forward_access_still_delivers_link(self):
        item = await self.queued()
        self.bot.forward.return_value = False
        await self.service.deliver_one(item)
        self.assertIn("https://t.me/Apartament_999/1", self.bot.message.call_args.args[0])
        self.assertEqual(self.store.counts()["sent"], 1)

    async def test_deleted_listing_is_not_sent(self):
        item = await self.queued()
        self.reader.messages.clear()
        await self.service.deliver_one(item)
        self.bot.message.assert_not_awaited()
        self.assertEqual(self.store.counts()["pending"], 0)

    async def test_price_change_rechecked_before_send(self):
        item = await self.queued()
        self.reader.messages[1].message = TEXT.replace("780", "900")
        await self.service.deliver_one(item)
        self.bot.message.assert_not_awaited()
        self.assertEqual(self.store.counts()["pending"], 0)

    async def test_paused_delivery_does_not_send(self):
        item = await self.queued()
        self.store.set_meta("paused", "true")
        await self.service.deliver_one(item)
        self.bot.message.assert_not_awaited()
        self.assertEqual(self.store.counts()["pending"], 1)

    async def test_overdue_quiet_waits_until_today_cutoff_after_downtime(self):
        item = await self.queued(TEXT.replace("780", "850"))
        morning = NOW.replace(hour=4)
        with patch("rentbot.service.quiet_due", return_value=NOW + timedelta(hours=1)):
            await self.service.deliver_one(item)
        self.bot.message.assert_not_awaited()
        self.assertEqual(self.store.due(NOW), [])
        self.assertEqual(self.store.counts()["pending"], 1)

    async def test_first_start_does_not_backfill(self):
        await self.service.initialize()
        await self.service.poll_once()
        self.assertEqual(self.store.counts()["pending"], 0)
        self.reader.messages[2] = message(2)
        await self.service.poll_once()
        self.assertEqual(self.store.counts()["pending"], 1)
        self.assertEqual(self.store.get_meta(self.service.cursor_key), "2")

    async def test_restart_catches_up_more_than_one_page(self):
        self.reader.messages = {i: message(i) for i in range(1, 551)}
        self.store.set_meta(self.service.cursor_key, "0")
        self.store.set_meta(self.service.floor_key, "0")
        self.service.pipeline.evaluate = AsyncMock()
        await self.service.poll_once()
        self.assertEqual(self.store.get_meta(self.service.cursor_key), "500")
        await self.service.poll_once()
        self.assertEqual(self.store.get_meta(self.service.cursor_key), "550")

    async def test_album_hydrated_across_page_boundary(self):
        self.reader.messages = {1: message(1, "", 88), 2: message(2, TEXT, 88)}
        result = await self.service.complete_album(SourcePost([1], "", 88))
        self.assertEqual(result.message_ids, [1, 2])
        self.assertEqual(result.text, TEXT)

    async def test_poll_fetches_missing_parts_of_multiple_albums_together(self):
        self.service.settings = replace(self.settings, edit_scan_limit=2)
        self.store.set_meta(self.service.cursor_key, "50")
        self.reader.messages = {m.id: m for m in (
            message(50, TEXT, 88), message(51, "", 88),
            message(60, TEXT, 99), message(61, "", 99),
        )}
        with patch.object(self.reader, "get_messages", wraps=self.reader.get_messages) as get_messages:
            with patch.object(self.service.pipeline, "evaluate", new_callable=AsyncMock) as evaluate:
                await self.service.poll_once()
        album_calls = [c.kwargs["ids"] for c in get_messages.await_args_list if "ids" in c.kwargs]
        self.assertEqual(len(album_calls), 1)
        self.assertIn(50, album_calls[0])
        self.assertNotIn(60, album_calls[0])
        posts = [c.args[0] for c in evaluate.await_args_list]
        self.assertEqual([(p.message_ids, p.text) for p in posts], [([50, 51], TEXT), ([60, 61], TEXT)])
        self.assertEqual(self.store.get_meta(self.service.cursor_key), "61")

    async def test_other_people_and_groups_cannot_control_bot(self):
        for chat, sender, kind in [(999, 999, "private"), (123, 999, "private"), (123, 123, "group")]:
            await handle_update({"message": {"chat": {"id": chat, "type": kind},
                                             "from": {"id": sender}, "text": "/pause"}}, self.bot, self.store)
        self.assertIsNone(self.store.get_meta("paused"))
        self.bot.message.assert_not_awaited()
        await handle_update({"message": {"chat": {"id": 123, "type": "private"},
                                         "from": {"id": 123}, "text": "/pause"}}, self.bot, self.store)
        self.assertEqual(self.store.get_meta("paused"), "true")
        self.bot.message.assert_awaited_once()

    async def test_bot_forwards_are_silent_even_for_loud_listing(self):
        bot = BotAPI("not-a-real-token", 123)
        bot.call = AsyncMock(return_value=[{"message_id": 11}])
        self.assertTrue(await bot.forward("Apartament_999", [1]))
        self.assertTrue(bot.call.call_args.kwargs["disable_notification"])

    async def test_bot_forward_denied_has_no_retry_but_429_retries(self):
        bot = BotAPI("not-a-real-token", 123)
        bot.call = AsyncMock(side_effect=APIError("Telegram", 403))
        self.assertFalse(await bot.forward("Apartament_999", [1]))
        bot.call.side_effect = APIError("Telegram", 429, 10)
        with self.assertRaises(APIError):
            await bot.forward("Apartament_999", [1])


class LockTests(unittest.TestCase):
    def test_second_process_lock_fails_and_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.lock"
            with single_instance(path):
                with self.assertRaises(RuntimeError):
                    with single_instance(path):
                        pass
            with single_instance(path):
                pass


if __name__ == "__main__":
    unittest.main()
