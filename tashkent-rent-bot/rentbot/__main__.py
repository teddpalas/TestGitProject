import argparse
import asyncio
from dataclasses import asdict
from datetime import date, datetime, timezone
import json
import logging
from pathlib import Path
import sys

from .config import Settings, load_env
from .parser import parse_listing
from .rules import classify
from .schedule import quiet_due


async def account(settings, *, login=False):
    from telethon import TelegramClient
    from .service import single_instance

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with single_instance(settings.data_dir / "run.lock"):
        client = TelegramClient(settings.session_path, settings.api_id, settings.api_hash,
                                receive_updates=False)
        try:
            if login:
                # Phone, login code and optional 2FA stay in this local terminal.
                await client.start()
            else:
                await client.connect()
                if not await client.is_user_authorized():
                    raise RuntimeError("Сначала выполните python -m rentbot login")
            me = await client.get_me()
            print(f"Ваш TELEGRAM_CHAT_ID={me.id}")
        finally:
            await client.disconnect()


def demo():
    text = ("Сдаётся квартира на длительный срок. Новостройка. Дом сдан 2025-04-01. "
            "2 комнаты, 45 м². Цена 780 USD в месяц. Никто не жил.")
    listing = parse_listing(text)
    # This is a fixed, clearly marked simulation, NOT a real route or property.
    listing.walking_minutes = 18
    decision = classify(listing, date(2026, 11, 16))
    print("ДЕМОНСТРАЦИЯ: вымышленное объявление, условный маршрут 18 минут.")
    print(json.dumps({"listing": asdict(listing), "decision": decision.as_dict()},
                     ensure_ascii=False, indent=2, default=str))
    now = datetime(2026, 11, 16, 4, 0, tzinfo=timezone.utc)
    print("Тихая отправка для понедельника 09:00 в Ташкенте (UTC):", quiet_due(now).isoformat())


def main(argv=None) -> int:
    # Windows redirected consoles can default to cp1251, which lacks м²/emoji.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Личный бот поиска аренды в Ташкенте")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("check-config", "login", "whoami", "run", "demo"):
        sub.add_parser(command)
    inspect = sub.add_parser("inspect", help="Разобрать текст без Telegram и без сетевых запросов")
    inspect.add_argument("file", type=Path)
    args = parser.parse_args(argv)
    if args.command == "demo":
        demo()
        return 0
    if args.command == "inspect":
        listing = parse_listing(args.file.read_text(encoding="utf-8-sig"))
        from .schedule import TASHKENT
        print(json.dumps({"listing": asdict(listing),
                          "decision": classify(listing, datetime.now(TASHKENT).date()).as_dict()},
                         ensure_ascii=False, indent=2, default=str))
        return 0
    try:
        load_env()
        settings = Settings.from_env()
        errors = settings.validate(reader_only=args.command in ("login", "whoami"))
        if errors:
            print("\n".join(errors), file=sys.stderr)
            return 2
        if args.command == "check-config":
            from .geo import apply_catalogue
            apply_catalogue(parse_listing("Проверка файла настроек"), settings.locations_file)
            print("Основные настройки заполнены. Секреты не выводятся.")
            print("Telegram и сервис маршрутов этой командой не проверяются.")
            print(f"Сервис пеших маршрутов: {settings.routing_provider}")
            if not settings.routing_key or not settings.office_location_confirmed:
                key_name = "GEOAPIFY_API_KEY" if settings.routing_provider == "geoapify" else "ORS_API_KEY"
                print(f"Маршруты не готовы: нужны {key_name} и подтверждённая точка офиса.")
            return 0
        logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
        logging.getLogger("rentbot").setLevel(logging.INFO)
        if args.command in ("login", "whoami"):
            asyncio.run(account(settings, login=args.command == "login"))
        else:
            from .service import run
            asyncio.run(run(settings))
        return 0
    except KeyboardInterrupt:
        print("Остановлено. Очередь сохранена.")
        return 0
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        # Do not expose auth/session details in the console or crash reports.
        print(f"Ошибка запуска: {type(exc).__name__}. Проверьте настройки и соединение.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
