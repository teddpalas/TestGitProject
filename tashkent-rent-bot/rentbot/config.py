"""Configuration stays on the user's machine; secrets are never logged."""

from dataclasses import dataclass, field
import math
import os
from pathlib import Path
import re


def load_env(path: str | Path = ".env") -> None:
    path = Path(path)
    if not path.exists():
        return
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f".env: строка {number} должна иметь вид ИМЯ=значение")
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError(f".env: неверное имя настройки в строке {number}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    api_id: int
    api_hash: str = field(repr=False)
    bot_token: str = field(repr=False)
    chat_id: int
    source_channel: str = "Apartament_999"
    data_dir: Path = Path("data")
    poll_seconds: int = 20
    edit_scan_limit: int = 100
    backfill_limit: int = 0
    office_lat: float | None = None
    office_lon: float | None = None
    office_location_confirmed: bool = False
    ors_api_key: str = field(default="", repr=False)
    locations_file: Path = Path("locations.json")
    routing_provider: str = "ors"
    geoapify_api_key: str = field(default="", repr=False)

    @classmethod
    def from_env(cls):
        def integer(name, default="0"):
            try:
                return int(os.environ.get(name, default) or default)
            except ValueError:
                raise ValueError(f"{name}: требуется целое число") from None

        def coordinate(name):
            raw = os.environ.get(name, "").strip()
            try:
                return float(raw) if raw else None
            except ValueError:
                raise ValueError(f"{name}: требуется число с десятичной точкой") from None

        return cls(
            api_id=integer("TELEGRAM_API_ID"),
            api_hash=os.environ.get("TELEGRAM_API_HASH", "").strip(),
            bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
            chat_id=integer("TELEGRAM_CHAT_ID"),
            source_channel=os.environ.get("SOURCE_CHANNEL", "Apartament_999").lstrip("@"),
            data_dir=Path(os.environ.get("DATA_DIR", "data")),
            poll_seconds=integer("POLL_SECONDS", "20"),
            edit_scan_limit=integer("EDIT_SCAN_LIMIT", "100"),
            backfill_limit=integer("BACKFILL_LIMIT", "0"),
            office_lat=coordinate("OFFICE_LAT"), office_lon=coordinate("OFFICE_LON"),
            office_location_confirmed=os.environ.get("OFFICE_LOCATION_CONFIRMED", "false").lower() == "true",
            ors_api_key=os.environ.get("ORS_API_KEY", "").strip(),
            locations_file=Path(os.environ.get("LOCATIONS_FILE", "locations.json")),
            routing_provider=os.environ.get("ROUTING_PROVIDER", "ors").strip().lower(),
            geoapify_api_key=os.environ.get("GEOAPIFY_API_KEY", "").strip(),
        )

    @property
    def session_path(self) -> str:
        return str(self.data_dir / "reader")

    @property
    def routing_key(self) -> str:
        return self.geoapify_api_key if self.routing_provider == "geoapify" else self.ors_api_key

    def validate(self, *, reader_only=False) -> list[str]:
        errors = []
        if self.api_id <= 0:
            errors.append("Заполните TELEGRAM_API_ID")
        if not re.fullmatch(r"[0-9a-fA-F]{32}", self.api_hash):
            errors.append("Заполните TELEGRAM_API_HASH (32 шестнадцатеричных символа)")
        if not reader_only:
            if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", self.bot_token):
                errors.append("Заполните TELEGRAM_BOT_TOKEN от BotFather")
            if self.chat_id <= 0:
                errors.append("TELEGRAM_CHAT_ID должен быть положительным ID вашего личного чата")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", self.source_channel):
            errors.append("SOURCE_CHANNEL должен быть публичным username без ссылки")
        if not 10 <= self.poll_seconds <= 300:
            errors.append("POLL_SECONDS: допустимо от 10 до 300 секунд")
        if not 1 <= self.edit_scan_limit <= 1000 or not 0 <= self.backfill_limit <= 1000:
            errors.append("EDIT_SCAN_LIMIT: 1–1000; BACKFILL_LIMIT: 0–1000")
        if (self.office_lat is None) != (self.office_lon is None):
            errors.append("Укажите обе координаты офиса")
        for name, value, bound in (("OFFICE_LAT", self.office_lat, 90), ("OFFICE_LON", self.office_lon, 180)):
            if value is not None and (not math.isfinite(value) or not -bound <= value <= bound):
                errors.append(f"Некорректная координата {name}")
        if self.office_location_confirmed and self.office_lat is None:
            errors.append("Сначала укажите координаты офиса, затем подтвердите их")
        if self.routing_provider not in {"geoapify", "ors"}:
            errors.append("ROUTING_PROVIDER: выберите geoapify или ors")
        return errors
