"""One reader, one durable outbox worker and private owner commands."""

import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path

from .geo import WalkingRouter
from .http import APIError
from .pipeline import Pipeline, SourcePost, group_messages
from .schedule import quiet_due
from .storage import Store
from .telegram import BotAPI, handle_update

log = logging.getLogger("rentbot")


@contextmanager
def single_instance(path: Path):
    """OS-released advisory lock; a crash does not leave a stale PID lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0)
        handle.write(b"0")
        handle.flush()
        handle.seek(0)
        try:
            import msvcrt
        except ImportError:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise RuntimeError("Бот уже запущен с этой DATA_DIR") from None
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
        else:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RuntimeError("Бот уже запущен с этой DATA_DIR") from None
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


class Service:
    def __init__(self, settings, reader, bot, store):
        self.settings, self.reader, self.bot, self.store = settings, reader, bot, store
        self.pipeline = Pipeline(settings, store, WalkingRouter(settings, store))
        self.entity = None
        self.lock = asyncio.Lock()
        self.cursor_key = f"cursor:{settings.source_channel}"
        self.floor_key = f"floor:{settings.source_channel}"

    async def initialize(self):
        self.entity = await self.reader.get_entity(self.settings.source_channel)
        if self.store.get_meta(self.cursor_key) is None:
            recent = await self.reader.get_messages(self.entity, limit=max(1, self.settings.backfill_limit))
            latest = max((m.id for m in recent), default=0)
            floor = max(0, min((m.id for m in recent), default=1) - 1) if self.settings.backfill_limit else latest
            self.store.set_meta(self.cursor_key, str(floor))
            self.store.set_meta(self.floor_key, str(floor))
            log.info("Начальная позиция сохранена; старые объявления по умолчанию пропускаются")

    async def complete_album(self, post: SourcePost) -> SourcePost:
        if post.group_id is None:
            return post
        # Telegram albums contain at most ten items. Inspect adjacent IDs so
        # a caption/album split at a page boundary is not silently lost.
        ids = list(range(max(1, min(post.message_ids) - 10), max(post.message_ids) + 11))
        messages = await self.reader.get_messages(self.entity, ids=ids)
        same = [m for m in messages if m is not None and getattr(m, "grouped_id", None) == post.group_id]
        return group_messages(same)[0] if same else post

    async def poll_once(self):
        cursor = int(self.store.get_meta(self.cursor_key, "0"))
        floor = int(self.store.get_meta(self.floor_key, "0"))
        new = []
        async for message in self.reader.iter_messages(self.entity, min_id=cursor, reverse=True, limit=500):
            # Let Telegram finish assembling very recent albums before reading.
            timestamp = message.date
            if (datetime.now(timezone.utc) - timestamp).total_seconds() < 3:
                break
            new.append(message)
        recent = await self.reader.get_messages(self.entity, limit=self.settings.edit_scan_limit)
        combined = {m.id: m for m in recent if m.id > floor and m.id <= cursor}
        combined.update({m.id: m for m in new})
        async with self.lock:
            for post in group_messages(combined.values()):
                post = await self.complete_album(post)
                await self.pipeline.evaluate(post)
            if new:
                self.store.set_meta(self.cursor_key, str(max(m.id for m in new)))
        self.store.set_meta("last_poll", datetime.now(timezone.utc).isoformat(timespec="seconds"))

    async def poll_loop(self):
        while True:
            try:
                await self.poll_once()
            except Exception as exc:
                # Avoid tracebacks/exception strings that can contain URLs or account data.
                self.record_error("Чтение канала", exc)
                await asyncio.sleep(max(self.settings.poll_seconds, getattr(exc, "seconds", 0)))
            else:
                await asyncio.sleep(self.settings.poll_seconds)

    def record_error(self, phase: str, error: Exception):
        detail = str(error) if isinstance(error, APIError) else type(error).__name__
        message = f"{phase}: {detail}"
        self.store.set_meta("last_error", message)
        log.warning(message)

    async def revalidate(self, item: dict):
        original = item["payload"]["post"]
        messages = await self.reader.get_messages(self.entity, ids=original["message_ids"])
        messages = [m for m in messages if m is not None and not getattr(m, "action", None)]
        if not messages:
            self.store.reject(item["key"], "deleted:" + item["revision"])
            return None
        posts = group_messages(messages)
        if not posts:
            self.store.reject(item["key"], "empty:" + item["revision"])
            return None
        post = await self.complete_album(posts[0])
        checked = await self.pipeline.evaluate(post)
        if checked["tier"] == "reject" or checked["revision"] != item["revision"]:
            return None
        return checked

    async def deliver_one(self, item: dict):
        async with self.lock:
            if self.store.get_meta("paused") == "true":
                return
            now = datetime.now(timezone.utc)
            if item["tier"] == "quiet" and quiet_due(now) > now:
                # An overdue queue after downtime or /pause still obeys today's schedule.
                self.store.retry(item["key"], item["revision"], quiet_due(now), "Ожидание 16:50")
                return
            checked = await self.revalidate(item)
            if checked is None:
                return
            payload = checked["payload"]
            stage = f"delivery:{item['key']}:{item['revision']}"
            if self.store.get_meta(stage) is None:
                await self.bot.message(payload["summary"], silent=item["tier"] != "loud")
                self.store.set_meta(stage, "summary_sent")
            # Only the summary can make a sound; forwards are always silent.
            if self.store.get_meta(stage) != "forwarded":
                forwarded = await self.bot.forward(payload["channel"], payload["message_ids"])
                if not forwarded:
                    log.info("Пересылка недоступна; доставлена карточка со ссылкой на оригинал")
                self.store.set_meta(stage, "forwarded")
            self.store.mark_sent(item["key"], item["revision"])

    async def delivery_loop(self):
        while True:
            if self.store.get_meta("paused") != "true":
                for item in self.store.due(datetime.now(timezone.utc)):
                    try:
                        await self.deliver_one(item)
                    except Exception as exc:
                        self.record_error("Доставка", exc)
                        delay = max(getattr(exc, "retry_after", 0), getattr(exc, "seconds", 0),
                                    min(3600, 10 * 2 ** min(item["attempts"], 8)))
                        self.store.retry(item["key"], item["revision"],
                                         datetime.now(timezone.utc) + timedelta(seconds=delay),
                                         type(exc).__name__)
                        # A FloodWait/rate limit applies to subsequent requests too.
                        await asyncio.sleep(min(delay, 60))
                        break
                    await asyncio.sleep(1.1)
            await asyncio.sleep(1)

    async def command_loop(self):
        while True:
            try:
                offset = int(self.store.get_meta("updates_offset", "0"))
                updates = await self.bot.call("getUpdates", offset=offset, timeout=20,
                                              allowed_updates=["message"])
                for update in updates:
                    await handle_update(update, self.bot, self.store)
                    self.store.set_meta("updates_offset", str(update["update_id"] + 1))
            except Exception as exc:
                self.record_error("Команды", exc)
                await asyncio.sleep(max(5, getattr(exc, "retry_after", 0)))

    async def serve(self):
        await self.initialize()
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(self.poll_loop())
            tasks.create_task(self.delivery_loop())
            tasks.create_task(self.command_loop())


async def run(settings):
    from telethon import TelegramClient

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with single_instance(settings.data_dir / "run.lock"), Store(settings.data_dir / "rentbot.sqlite3") as store:
        bot = BotAPI(settings.bot_token, settings.chat_id)
        await bot.call("getMe")
        if (await bot.call("getWebhookInfo")).get("url"):
            raise RuntimeError("У этого бота уже настроен webhook. Используйте отдельного бота без webhook")
        reader = TelegramClient(settings.session_path, settings.api_id, settings.api_hash,
                                flood_sleep_threshold=0, receive_updates=False)
        await reader.connect()
        try:
            if not await reader.is_user_authorized():
                raise RuntimeError("Сначала выполните python -m rentbot login")
            log.info("Бот запущен; журнал без токенов и текстов объявлений")
            await Service(settings, reader, bot, store).serve()
        finally:
            await reader.disconnect()
