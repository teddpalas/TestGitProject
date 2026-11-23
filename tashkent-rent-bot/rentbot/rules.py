"""Agreed rental criteria, independent of Telegram, storage and networking."""

from __future__ import annotations

import calendar
import math
from datetime import date

from .models import Decision, Listing

MAX_BUILDING_AGE_YEARS = 5
LOUD_MAX_PRICE_USD = 750
QUIET_MAX_PRICE_USD = 800
LOUD_MAX_WALK_MINUTES = 20
QUIET_MAX_WALK_MINUTES = 25


def _building_age_cutoff(today: date) -> date:
    year = today.year - MAX_BUILDING_AGE_YEARS
    return date(year, today.month, min(today.day, calendar.monthrange(year, today.month)[1]))


def classify(listing: Listing, today: date) -> Decision:
    reasons: list[str] = []
    unknowns: list[str] = []
    deviations: list[str] = []

    if listing.is_rental is False:
        reasons.append("Не актуальное предложение аренды квартиры")
    elif listing.is_rental is None:
        unknowns.append("Тип объявления: аренда не подтверждена")
    if listing.is_long_term is False:
        reasons.append("Краткосрочная аренда")
    elif listing.is_long_term is None:
        unknowns.append("Срок аренды")

    if listing.rooms is None:
        unknowns.append("Количество комнат")
    elif not isinstance(listing.rooms, int) or isinstance(listing.rooms, bool) or listing.rooms < 2:
        reasons.append("Меньше двух комнат или некорректное число комнат")

    def numeric(value: float | None, label: str, hard_min: float | None = None,
                strict_max: float | None = None, relaxed_max: float | None = None) -> None:
        if value is None:
            unknowns.append(label)
        elif not isinstance(value, (float, int)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            reasons.append(f"Некорректное значение: {label}")
        elif hard_min is not None and value < hard_min:
            reasons.append(f"{label}: меньше {hard_min:g}")
        elif relaxed_max is not None and value > relaxed_max:
            reasons.append(f"{label}: больше {relaxed_max:g}")
        elif strict_max is not None and value > strict_max:
            deviations.append(label)

    numeric(listing.area_m2, "Площадь, м²", hard_min=40)
    numeric(listing.price_usd, "Аренда, $/месяц",
            strict_max=LOUD_MAX_PRICE_USD, relaxed_max=QUIET_MAX_PRICE_USD)
    numeric(listing.walking_minutes, "Пешком до офиса, минут",
            strict_max=LOUD_MAX_WALK_MINUTES, relaxed_max=QUIET_MAX_WALK_MINUTES)

    cutoff = _building_age_cutoff(today)
    if listing.is_new_building is False:
        reasons.append("Дом не соответствует требованию сданной новостройки")
    elif listing.commissioned_on is not None:
        if not cutoff <= listing.commissioned_on <= today:
            reasons.append(f"Дом старше {MAX_BUILDING_AGE_YEARS} лет или ещё не сдан")
        if listing.commissioned_year is not None and listing.commissioned_year != listing.commissioned_on.year:
            reasons.append("Противоречивые дата и год сдачи дома")
    elif listing.commissioned_year is not None:
        year = listing.commissioned_year
        if year < 1 or year > today.year:
            reasons.append("Некорректный или будущий год сдачи дома")
        elif date(year, 12, 31) < cutoff:
            reasons.append(f"Дом старше {MAX_BUILDING_AGE_YEARS} лет")
        elif date(year, 1, 1) < cutoff:
            unknowns.append("Точная дата сдачи дома: пограничный год")
    else:
        unknowns.append("Дата сдачи дома: возраст не подтверждён")

    if len(unknowns) > 2:
        reasons.append("Неизвестны более двух критериев")
    if unknowns and deviations:
        reasons.append("Для неполного объявления остальные параметры должны строго подходить")
    # A post with no evidence that it offers a rental cannot enter the queue.
    if listing.is_rental is not True:
        if listing.is_rental is None:
            reasons.append("Нет подтверждения, что предлагается квартира в аренду")
    tier = "reject" if reasons else ("quiet" if unknowns or deviations else "loud")
    return Decision(tier=tier, reasons=tuple(reasons), unknowns=tuple(unknowns), deviations=tuple(deviations))
