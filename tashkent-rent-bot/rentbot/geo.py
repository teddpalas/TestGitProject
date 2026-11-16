"""Only explicit pins or an owner-confirmed address catalogue produce routes."""

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re

from .http import APIError, post_json
from .models import Listing


def normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold().replace("ё", "е")).strip()


def apply_catalogue(listing: Listing, path: Path) -> None:
    if not path.exists():
        return
    entries = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(entries, list):
        raise ValueError("LOCATIONS_FILE: ожидается список объектов")
    text = normalized(listing.text)
    matches = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("confirmed") is not True:
            continue
        if not entry.get("source"):
            raise ValueError("Подтверждённому адресу нужен source с источником проверки")
        aliases = entry.get("aliases", [])
        if not isinstance(aliases, list):
            raise ValueError("aliases должен быть списком")
        matched = False
        for alias in aliases:
            if not isinstance(alias, str) or len(normalized(alias)) < 5:
                continue
            for match in re.finditer(r"(?<!\w)" + re.escape(normalized(alias)) + r"(?!\w)", text):
                prefix = text[max(0, match.start() - 45):match.start()]
                if not re.search(r"(?:ориентир|рядом|возле|около|напротив|недалеко|близко)\s*(?:с\s*)?[:—–-]?\s*$", prefix):
                    matched = True
        if matched:
            matches.append(entry)
    if len(matches) > 1:
        listing.warnings.append("Адрес совпал с несколькими записями справочника")
        return
    if not matches:
        return
    entry = matches[0]
    lat, lon = entry.get("latitude"), entry.get("longitude")
    if lat is not None and lon is not None:
        lat, lon = float(lat), float(lon)
        if not all(math.isfinite(x) for x in (lat, lon)) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("Неверные координаты в LOCATIONS_FILE")
        if listing.latitude is None:
            listing.latitude, listing.longitude = lat, lon
            listing.evidence["location"] = f"Подтверждённый справочник: {entry['source']}"
        elif abs(listing.latitude - lat) > 0.001 or abs(listing.longitude - lon) > 0.001:
            listing.latitude = listing.longitude = None
            listing.warnings.append("Координаты объявления противоречат справочнику")
    if entry.get("commissioned_on"):
        commissioned = date.fromisoformat(entry["commissioned_on"])
        if listing.commissioned_on and listing.commissioned_on != commissioned:
            listing.commissioned_on = listing.commissioned_year = None
            listing.warnings.append("Дата сдачи дома противоречит справочнику")
        elif listing.commissioned_year and listing.commissioned_year != commissioned.year:
            listing.commissioned_on = listing.commissioned_year = None
            listing.warnings.append("Год сдачи дома противоречит справочнику")
        else:
            listing.commissioned_on = commissioned
            # A catalogue never overrides an explicitly old building claim.
            if listing.is_new_building is None:
                listing.is_new_building = True
            listing.evidence["commissioned_on"] = f"Подтверждённый справочник: {entry['source']}"


class WalkingRouter:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store

    async def enrich(self, listing: Listing) -> None:
        apply_catalogue(listing, self.settings.locations_file)
        settings = self.settings
        if listing.latitude is None or listing.longitude is None:
            return
        if not settings.office_location_confirmed or not settings.ors_api_key:
            listing.warnings.append("Пешеходный маршрут не настроен")
            return
        coordinates = [[listing.longitude, listing.latitude], [settings.office_lon, settings.office_lat]]
        key = "route:" + hashlib.sha256(json.dumps(coordinates).encode()).hexdigest()
        cached = self.store.get_meta(key)
        now = datetime.now(timezone.utc)
        if cached:
            record = json.loads(cached)
            if datetime.fromisoformat(record["expires"]) > now:
                listing.walking_minutes = record["minutes"]
                listing.evidence["walking_minutes"] = "Пешеходный маршрут openrouteservice / OpenStreetMap"
                return
        try:
            result = await post_json(
                "https://api.openrouteservice.org/v2/directions/foot-walking/json",
                {"coordinates": coordinates, "instructions": False, "geometry": False,
                 "radiuses": [100, 100]},
                headers={"Authorization": settings.ors_api_key}, service="openrouteservice")
            minutes = float(result["routes"][0]["summary"]["duration"]) / 60
            if not math.isfinite(minutes) or minutes < 0:
                raise ValueError("Invalid route duration")
        except (APIError, KeyError, IndexError, ValueError, TypeError):
            listing.warnings.append("Не удалось проверить пешеходный маршрут")
            return
        listing.walking_minutes = minutes
        listing.evidence["walking_minutes"] = "Пешеходный маршрут openrouteservice / OpenStreetMap"
        self.store.set_meta(key, json.dumps({"minutes": minutes, "expires": (now + timedelta(days=7)).isoformat()}))
