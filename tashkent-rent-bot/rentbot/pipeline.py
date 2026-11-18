"""Turn a Telegram post into a durable, explained delivery decision."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math

from .geo import normalized
from .parser import parse_listing
from .rules import classify
from .schedule import TASHKENT, quiet_due


@dataclass
class SourcePost:
    message_ids: list[int]
    text: str
    group_id: int | None = None
    media_ids: list[str] = field(default_factory=list)
    latitude: float | None = None
    longitude: float | None = None

    @property
    def source_id(self) -> str:
        return f"album:{self.group_id}" if self.group_id else f"message:{min(self.message_ids)}"


def group_messages(messages) -> list[SourcePost]:
    buckets = {}
    for message in sorted(messages, key=lambda x: x.id):
        if getattr(message, "action", None) is not None:
            continue
        group_id = getattr(message, "grouped_id", None)
        key = ("album", group_id) if group_id else ("message", message.id)
        buckets.setdefault(key, []).append(message)
    result = []
    for (kind, value), parts in buckets.items():
        texts = list(dict.fromkeys(m.message for m in parts if getattr(m, "message", None)))
        media_ids = []
        latitude = longitude = None
        for message in parts:
            for attr in ("photo", "document"):
                media = getattr(message, attr, None)
                if media is not None:
                    media_ids.append(f"{attr}:{media.id}")
            geo = getattr(message, "geo", None)
            if geo is not None:
                latitude, longitude = geo.lat, geo.long
        result.append(SourcePost([m.id for m in parts], "\n".join(texts),
                                 value if kind == "album" else None,
                                 sorted(media_ids), latitude, longitude))
    return result


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    default=str, allow_nan=False).encode()).hexdigest()


def explain(listing, decision, link: str) -> str:
    def value(number, suffix):
        return f"{number:g}{suffix}" if number is not None else "не указано"
    title = "🔔 Полное совпадение по имеющимся данным" if decision.tier == "loud" else "🔕 Вариант для проверки"
    walking = f"{math.ceil(listing.walking_minutes)} мин" if listing.walking_minutes is not None else "не подтверждено"
    age = str(listing.commissioned_on or listing.commissioned_year or "не указан")
    occupancy = {True: "ранее жили", False: "никто не жил", None: "неизвестно"}[listing.previously_occupied]
    lines = [title, f"{value(listing.rooms, ' комн.')} · {value(listing.area_m2, ' м²')} · {value(listing.price_usd, ' $/мес.')}",
             f"Пешком до офиса: {walking}", f"Сдача дома: {age}; {occupancy}."]
    if decision.deviations:
        lines.append("Отклонение: " + "; ".join(decision.deviations))
    if decision.unknowns:
        lines.append("Уточнить: " + "; ".join(decision.unknowns))
    if listing.warnings:
        lines.append("Примечание: " + "; ".join(listing.warnings))
    lines.extend(["Коммунальные, залог и комиссия — отдельно; условия и фото в оригинале.", link])
    if listing.walking_minutes is not None:
        if listing.evidence.get("walking_provider") == "geoapify":
            lines.append("Маршрут: Geoapify — https://www.geoapify.com/ · © OpenStreetMap contributors — https://www.openstreetmap.org/copyright")
        else:
            lines.append("Маршрут: openrouteservice / © OpenStreetMap contributors.")
    return "\n".join(lines)[:3800]


class Pipeline:
    def __init__(self, settings, store, router):
        self.settings, self.store, self.router = settings, store, router

    async def evaluate(self, post: SourcePost, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        listing = parse_listing(post.text)
        if post.latitude is not None:
            listing.latitude, listing.longitude = post.latitude, post.longitude
            listing.evidence["location"] = "Геометка Telegram"
        await self.router.enrich(listing)
        decision = classify(listing, now.astimezone(TASHKENT).date())
        alias = f"alias:{self.settings.source_channel}:{post.source_id}"
        # Reposts with identical caption AND media are merged. Edited originals
        # retain their key even when price or other details change.
        key = self.store.get_meta(alias)
        if key is None:
            key = digest([self.settings.source_channel, normalized(post.text), post.media_ids])
            self.store.set_meta(alias, key)
        facts = asdict(listing)
        for field_name in ("text", "evidence", "warnings"):
            facts.pop(field_name)
        revision = digest([facts, decision.as_dict()])
        link = f"https://t.me/{self.settings.source_channel}/{min(post.message_ids)}"
        payload = {"channel": self.settings.source_channel, "message_ids": post.message_ids,
                   "summary": explain(listing, decision, link), "post": asdict(post)}
        if decision.tier == "reject":
            self.store.reject(key, revision)
        else:
            due = now if decision.tier == "loud" else quiet_due(now)
            self.store.enqueue(key, revision, decision.tier, payload, due)
        return {"key": key, "revision": revision, "tier": decision.tier,
                "payload": payload, "decision": decision, "listing": listing}
