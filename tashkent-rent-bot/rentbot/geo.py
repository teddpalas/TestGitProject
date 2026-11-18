"""Only explicit pins or an owner-confirmed address catalogue produce routes."""

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re

from .http import APIError, get_json, post_json
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


def _minutes(duration) -> float:
    if isinstance(duration, bool):
        raise ValueError("Invalid route duration")
    minutes = float(duration) / 60
    if not math.isfinite(minutes) or minutes < 0:
        raise ValueError("Invalid route duration")
    return minutes


def _distance_metres(first, second) -> float:
    """Distance is used only to validate snapped endpoints, never as a route."""
    lon1, lat1 = first[:2]
    lon2, lat2 = second[:2]
    values = (lon1, lat1, lon2, lat2)
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) for value in values):
        raise ValueError("Invalid route coordinates")
    if not (-180 <= lon1 <= 180 and -180 <= lon2 <= 180
            and -90 <= lat1 <= 90 and -90 <= lat2 <= 90):
        raise ValueError("Invalid route coordinates")
    lat1, lat2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    haversine = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(min(1, max(0, haversine))))


def _geoapify_minutes(result: dict, coordinates: list) -> float:
    feature = result["features"][0]
    properties = feature["properties"]
    if properties.get("mode", "walk") != "walk":
        raise ValueError("Unexpected route mode")
    geometry = feature["geometry"]
    if geometry["type"] == "MultiLineString":
        lines = geometry["coordinates"]
    elif geometry["type"] == "LineString":
        lines = [geometry["coordinates"]]
    else:
        raise ValueError("Unexpected route geometry")
    if not isinstance(lines, list) or not lines or any(not isinstance(line, list) or len(line) < 2 for line in lines):
        raise ValueError("Missing route geometry")
    for actual, requested in ((lines[0][0], coordinates[0]), (lines[-1][-1], coordinates[1])):
        if not isinstance(actual, list) or len(actual) < 2 or _distance_metres(actual, requested) > 100:
            raise ValueError("Route endpoint too far from requested pin")
    return _minutes(properties["time"])


class WalkingRouter:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store

    async def enrich(self, listing: Listing) -> None:
        listing.walking_minutes = None
        listing.evidence.pop("walking_minutes", None)
        listing.evidence.pop("walking_provider", None)
        apply_catalogue(listing, self.settings.locations_file)
        settings = self.settings
        if listing.latitude is None or listing.longitude is None:
            return
        provider = settings.routing_provider
        if not settings.office_location_confirmed or not settings.routing_key or provider not in ("ors", "geoapify"):
            listing.warnings.append("Пешеходный маршрут не настроен")
            return
        coordinates = [[listing.longitude, listing.latitude], [settings.office_lon, settings.office_lat]]
        key = "route:" + provider + ":" + hashlib.sha256(json.dumps(coordinates).encode()).hexdigest()
        attribution = "Geoapify" if provider == "geoapify" else "openrouteservice"
        cached = self.store.get_meta(key)
        now = datetime.now(timezone.utc)
        if cached:
            try:
                record = json.loads(cached)
                if isinstance(record["minutes"], bool) or not isinstance(record["minutes"], (int, float)):
                    raise ValueError("Invalid cached route duration")
                minutes = _minutes(record["minutes"] * 60)
                if datetime.fromisoformat(record["expires"]) > now:
                    listing.walking_minutes = minutes
                    listing.evidence["walking_minutes"] = f"Пешеходный маршрут {attribution} / OpenStreetMap"
                    listing.evidence["walking_provider"] = provider
                    return
            except (KeyError, ValueError, TypeError, OverflowError):
                pass  # A damaged cache entry must not establish a walking time.
        try:
            if provider == "geoapify":
                result = await get_json(
                    "https://api.geoapify.com/v1/routing",
                    {"waypoints": f"{listing.latitude},{listing.longitude}|{settings.office_lat},{settings.office_lon}",
                     "mode": "walk", "format": "geojson", "apiKey": settings.routing_key},
                    service="Geoapify")
                minutes = _geoapify_minutes(result, coordinates)
            else:
                result = await post_json(
                    "https://api.heigit.org/openrouteservice/v2/directions/foot-walking/json",
                    {"coordinates": coordinates, "instructions": False, "geometry": False,
                     "radiuses": [100, 100]},
                    headers={"Authorization": settings.routing_key}, service="openrouteservice")
                minutes = _minutes(result["routes"][0]["summary"]["duration"])
        except (APIError, KeyError, IndexError, ValueError, TypeError, AttributeError, OverflowError):
            listing.warnings.append("Не удалось проверить пешеходный маршрут")
            return
        listing.walking_minutes = minutes
        listing.evidence["walking_minutes"] = f"Пешеходный маршрут {attribution} / OpenStreetMap"
        listing.evidence["walking_provider"] = provider
        self.store.set_meta(key, json.dumps({"minutes": minutes, "expires": (now + timedelta(days=7)).isoformat()}))
