"""Conservative, deterministic extraction; missing facts stay unknown.

The channel is untrusted input. Text never supplies walking time and never
executes commands. Only explicit dates/years establish a building's age.
"""

from __future__ import annotations

import re
from datetime import date

from .models import Listing


_NUMBER = r"(?:\d{1,3}(?:[ \u00a0]\d{3})+|\d+)(?:[.,]\d+)?"
_MONEY = re.compile(
    rf"(?:\$\s*(?P<before>{_NUMBER})|(?P<after>{_NUMBER})\s*(?:\$|usd\b|доллар\w*|у\.?\s*е\.?))",
    re.I,
)


def _number(value: str) -> float:
    return float(value.replace(" ", "").replace("\u00a0", "").replace(",", "."))


def _money_number(value: str) -> float:
    if re.fullmatch(r"\d{1,3}[,.]\d{3}", value):
        return float(value.replace(",", "").replace(".", ""))
    return _number(value)


def _unique_value(listing: Listing, name: str, candidates: list[tuple[object, str]]) -> None:
    values = {value for value, _ in candidates}
    if len(values) == 1:
        setattr(listing, name, candidates[0][0])
        listing.evidence[name] = candidates[0][1].strip()
    elif len(values) > 1:
        listing.warnings.append(f"Противоречивые значения: {name}")


def _parse_price(text: str, listing: Listing) -> None:
    explicit: list[tuple[float, str]] = []
    fallback: list[tuple[float, str]] = []
    for line in text.splitlines():
        if re.search(r"\d+\s*[-–—]\s*\$?\s*\d+\s*(?:\$|usd)|\$\s*\d+\s*[-–—]\s*\$?\s*\d+", line):
            listing.warnings.append("Цена указана диапазоном")
            continue
        for match in _MONEY.finditer(line):
            # Associate the amount with its nearest preceding field label.
            prefix = line[:match.start()]
            labels = list(re.finditer(
                r"цена|стоимость|аренда|ijara|narx\w*|ойлик|oylik|депозит|залог|комисси\w*|услуг\w*|коммунал\w*|deposit|коммуналь\w*",
                prefix, re.I,
            ))
            label = labels[-1].group().lower() if labels else ""
            if re.match(r"депозит|залог|комисси|услуг|коммун|deposit", label):
                continue
            if re.match(r"\s*[-—–:(]?\s*(?:депозит|залог|комисси\w*|коммунал\w*|deposit)\b", line[match.end():]):
                continue
            # Prices expressed per day, per m², as ranges or negotiable targets
            # are not silently promoted to a definite monthly rental price.
            surrounding = line[max(0, match.start() - 12):match.end() + 15]
            if re.search(r"(?:от|до)\s*\$?\s*$", prefix, re.I):
                listing.warnings.append("Указана граница цены, а не точная месячная плата")
                continue
            if re.search(r"/\s*(?:м|m)\s*[²2]|за\s*(?:м|m)\s*[²2]|(?:в|за|/)\s*(?:сутки|день|kun)", surrounding):
                continue
            amount = _money_number(match.group("before") or match.group("after"))
            entry = (amount, match.group())
            if label or re.search(r"(?:в\s+месяц|/\s*мес|за\s+месяц|oyiga)", line):
                explicit.append(entry)
            else:
                fallback.append(entry)
    _unique_value(listing, "price_usd", explicit or fallback)


def _parse_building(text: str, listing: Listing) -> None:
    if re.search(r"стар(?:ый|ого)\s+(?:дом|фонд)|хрущ[её]вк|сталинк|eski\s+uy|дом\s+не\s+сдан|строящ\w*\s+дом", text):
        listing.is_new_building = False
        listing.evidence["is_new_building"] = "Указан старый дом/фонд"
    elif re.search(r"новострой|нов(?:ый|ом|ого)\s+дом|yangi\s+uy|yangi\s+quril", text):
        listing.is_new_building = True
        listing.evidence["is_new_building"] = "Указана новостройка"

    labels = r"(?:дом\s+(?:сдан|построен)|введ[её]н\s+в\s+эксплуатацию|год\s+(?:постройки|сдачи)|сдача\s+дома|построен\s+в|qurilgan|foydalanishga\s+topshirilgan)"
    dates: list[tuple[date, str]] = []
    years: list[tuple[int, str]] = []
    for match in re.finditer(rf"{labels}\s*[:—–-]?\s*(?:в\s+)?(?P<value>\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}[./]\d{{1,2}}[./]\d{{4}}|(?:19|20)\d{{2}})", text):
        raw = match.group("value")
        try:
            if len(raw) == 4:
                years.append((int(raw), match.group()))
            elif "-" in raw:
                dates.append((date.fromisoformat(raw), match.group()))
            else:
                day, month, year = map(int, re.split(r"[./]", raw))
                dates.append((date(year, month, day), match.group()))
        except ValueError:
            listing.warnings.append("Некорректная дата сдачи дома")
    _unique_value(listing, "commissioned_on", dates)
    _unique_value(listing, "commissioned_year", years)
    if listing.commissioned_on and listing.commissioned_year:
        if listing.commissioned_on.year != listing.commissioned_year:
            listing.commissioned_on = None
            listing.commissioned_year = None
            listing.warnings.append("Дата и год сдачи дома противоречат друг другу")

    never = re.search(r"никто\s+(?:ещ[её]\s+)?не\s+жил|никто\s+не\s+проживал|без\s+проживания|первое\s+заселение|hech\s+kim\s+yashamagan", text)
    if never:
        context = text[max(0, never.start() - 45):never.end() + 45]
        if re.search(r"после\s+(?:нового\s+|свежего\s+|капитального\s+)?ремонт|после\s+отделки|после\s+собственник", context):
            never = None
            listing.warnings.append("Отсутствие проживания только после ремонта не подтверждает первое заселение")
    # 'First rental' does not prove that the owner has never lived there.
    used = re.search(r"ранее\s+(?:уже\s+)?(?:жили|проживали)|(?:квартира\s+)?уже\s+сдавалась|жил[аи]\s+(?:собственник|владелец)|жили\s+(?:владельцы|хозяева)|не\s+перв(?:ый\s+заезд|ое\s+заселение)|avval\s+yashagan", text)
    if never and used:
        listing.warnings.append("Противоречивые сведения о прежнем проживании")
    elif never:
        listing.previously_occupied = False
        listing.evidence["previously_occupied"] = never.group()
    elif used:
        listing.previously_occupied = True
        listing.evidence["previously_occupied"] = used.group()


def _parse_coordinates(text: str, listing: Listing) -> None:
    # Only explicit geographic coordinates, no approximate district geocoding.
    patterns = (
        (r"(?:координаты|coordinates|геопозиция)\s*[:=]?\s*(-?\d{1,2}\.\d{3,})\s*[,; ]\s*(-?\d{1,3}\.\d{3,})", False),
        (r"https?://(?:www\.)?(?:google\.[a-z.]+/maps|maps\.google\.[a-z.]+)[^\s]*[?&](?:q|query)=(-?\d{1,2}\.\d{3,})(?:,|%2c)(-?\d{1,3}\.\d{3,})", False),
        (r"https?://(?:www\.)?yandex\.[a-z.]+/maps[^\s]*[?&]pt=(-?\d{1,3}\.\d{3,})(?:,|%2c)(-?\d{1,2}\.\d{3,})", True),
    )
    candidates: set[tuple[float, float]] = set()
    for pattern, reverse in patterns:
        for match in re.finditer(pattern, text, re.I):
            first, second = float(match.group(1)), float(match.group(2))
            lat, lon = (second, first) if reverse else (first, second)
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                candidates.add((lat, lon))
    if len(candidates) == 1:
        listing.latitude, listing.longitude = candidates.pop()
        listing.evidence["coordinates"] = "Явные координаты из объявления"
    elif len(candidates) > 1:
        listing.warnings.append("Несколько разных точек на карте")


def parse_listing(text: str) -> Listing:
    listing = Listing(text=text)
    normalized = text.lower().replace("\u00a0", " ").replace("’", "'").replace("ʻ", "'")

    sale = re.search(r"прода[её]тся|продажа|срочно\s+продам|sotiladi|sotuv", normalized)
    unavailable = re.search(r"(?:квартира\s+)?(?:сдана|продана)\b|объявление\s+(?:неактуально|снято)|(?:^|\n)\s*(?:сдано|снято|неактуально)\b|уже\s+сдали|не\s+сда[её]тся|ijaraga\s+berildi", normalized)
    seeking = re.search(r"(?:^|\n)\s*(?:#?сниму|ищу\s+квартиру|снимем|куплю|нужна\s+квартира)", normalized)
    commercial = re.search(
        r"(?:сда[её]тся|сдам|аренда)\s+(?:(?:новый|нового|большой|большого)\s+)?(?:офис\w*|магазин\w*|склад\w*|коммерческ\w*)|"
        r"(?:офис|магазин|склад|коммерческое\s+помещение)\s+(?:в\s+аренду|сда[её]тся)|"
        r"(?:^|\n)\s*(?:#?офис\b|коммерческ\w*\s+помещен)", normalized,
    )
    shared = re.search(
        r"подселени|койко[ -]?мест|(?:сда[её]тся|сдам|аренда)\s+(?:одной\s+|одну\s+)?комнат[аууы]\b|"
        r"(?:^|\n)\s*комната\s+(?:в|для)\b", normalized,
    )
    rental = re.search(r"аренд[ауы]|сда[её]тся|сда[её]м|сдам|сдача\s+квартир|ijara|ижара", normalized)
    daily = re.search(r"посуточ|почасов|на\s+сутки|kunlik|sutkalik|soatlik", normalized)
    long_term = re.search(r"долгосроч|длительн\w*\s+срок|на\s+(?:год|долгий\s+срок)|uzoq\s+muddat|узоқ\s+муддат", normalized)
    if sale or unavailable or seeking or commercial or shared:
        listing.is_rental = False
        listing.evidence["is_rental"] = (sale or unavailable or seeking or commercial or shared).group()
    elif rental:
        listing.is_rental = True
        listing.evidence["is_rental"] = rental.group()
    if daily:
        listing.is_long_term = False
        listing.evidence["is_long_term"] = daily.group()
    elif long_term:
        listing.is_long_term = True
        listing.is_rental = True if listing.is_rental is None else listing.is_rental
        listing.evidence["is_long_term"] = long_term.group()

    room_candidates: list[tuple[int, str]] = []
    euro = re.search(r"евро[\s-]*(?:двуш|тр[её]ш|[234])|euro[\s-]*[234]", normalized)
    if euro:
        listing.warnings.append("Европланировка: число обычных комнат требует уточнения")
    else:
        room_patterns = (
            r"(?<!\d)(\d{1,2})\s*(?:[-–]\s*)?(?:х\s*[-–]?\s*)?(?:комнат\w*|комн\.?|xonali|xona|хонали|хона)\b",
            r"(?:комнат\w*|комн\.?|xonalar)\s*[:—–-]\s*(\d{1,2})\b",
            r"(?<![\d/])(\d{1,2})\s*/\s*\d{1,2}\s*/\s*\d{1,2}(?![\d/])",
        )
        for pattern in room_patterns:
            room_candidates.extend((int(m.group(1)), m.group()) for m in re.finditer(pattern, normalized))
        _unique_value(listing, "rooms", room_candidates)

    total_areas: list[tuple[float, str]] = []
    ordinary_areas: list[tuple[float, str]] = []
    for line in normalized.splitlines():
        for match in re.finditer(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(?:м\s*[²2]|m\s*[²2]|кв\.?\s*м\.?|kv\.?\s*m\.?)", line):
            prefix = line[:match.start()]
            if re.search(r"(?:кухн\w*|жил\w*|балкон\w*)\s*(?:площадь\s*)?[:—–-]?\s*$", prefix):
                continue
            value = (_number(match.group(1)), match.group())
            if re.search(r"общ\w*\s*(?:площадь)?\s*[:—–-]?\s*$", prefix):
                total_areas.append(value)
            else:
                ordinary_areas.append(value)
        for match in re.finditer(r"(?:общая\s+площадь|площадь|maydon\w*|майдон\w*)\s*[:—–-]\s*(\d+(?:[.,]\d+)?)\b", line):
            if re.search(r"жил\w*\s*$", line[:match.start()]):
                continue
            total_areas.append((_number(match.group(1)), match.group()))
    _unique_value(listing, "area_m2", total_areas or ordinary_areas)

    _parse_price(normalized, listing)
    _parse_building(normalized, listing)
    _parse_coordinates(normalized, listing)
    return listing
