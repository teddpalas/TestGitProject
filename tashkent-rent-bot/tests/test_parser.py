import unittest
from datetime import date

from rentbot.parser import parse_listing


class ParserTests(unittest.TestCase):
    def test_complete_russian_listing(self):
        listing = parse_listing("Сдаётся долгосрочно. Новостройка. Дом сдан 12.01.2025. Никто не жил.\n2-комнатная, 48,5 м²\nЦена: 800$\nКоординаты: 41.296031, 69.259668")
        self.assertEqual((listing.rooms, listing.area_m2, listing.price_usd), (2, 48.5, 800))
        self.assertEqual(listing.commissioned_on, date(2025, 1, 12))
        self.assertFalse(listing.previously_occupied)
        self.assertTrue(listing.is_long_term)
        self.assertEqual((listing.latitude, listing.longitude), (41.296031, 69.259668))

    def test_uzbek(self):
        listing = parse_listing("Uzoq muddatga ijara. Yangi uy. Qurilgan 2025. Hech kim yashamagan. 2 xonali\nMaydoni: 45\nNarxi: 750 USD")
        self.assertEqual((listing.rooms, listing.area_m2, listing.price_usd), (2, 45, 750))
        self.assertEqual(listing.commissioned_year, 2025)
        self.assertTrue(listing.is_long_term)
        self.assertFalse(listing.previously_occupied)

    def test_floor_notation(self):
        self.assertEqual(parse_listing("Аренда: 2/5/9, 50 м2, $800").rooms, 2)

    def test_euro_two_is_not_confirmed_two_rooms(self):
        self.assertIsNone(parse_listing("Евродвушка, 2 комнаты, 45 м²").rooms)

    def test_deposit_does_not_become_price(self):
        listing = parse_listing("Аренда 800$, залог 400$, комиссия 200$\nДепозит: $500")
        self.assertEqual(listing.price_usd, 800)
        self.assertIsNone(parse_listing("Сдаётся квартира\nДепозит: 500$").price_usd)
        self.assertEqual(parse_listing("Аренда квартиры\n800$ + депозит800$").price_usd, 800)

    def test_price_thousands_and_sum_unknown(self):
        self.assertEqual(parse_listing("Цена: 1 200 USD").price_usd, 1200)
        self.assertEqual(parse_listing("Цена: $1200").price_usd, 1200)
        self.assertEqual(parse_listing("Цена: $1,200").price_usd, 1200)
        self.assertIsNone(parse_listing("Цена: 10 000 000 сум").price_usd)

    def test_price_ranges_are_unknown(self):
        self.assertIsNone(parse_listing("Цена: $700-900").price_usd)
        self.assertIsNone(parse_listing("Цена: 750–850$").price_usd)
        self.assertIsNone(parse_listing("Аренда\n500$ залог").price_usd)

    def test_conflicting_prices_unknown(self):
        self.assertIsNone(parse_listing("Цена: $750\nЦена: $850").price_usd)
        self.assertIsNone(parse_listing("Аренда, 700$ или 900$ с мебелью").price_usd)

    def test_rooms_on_separate_lines(self):
        self.assertEqual(parse_listing("Комнаты: 2\nЭтаж: 9\nЭтажность: 12").rooms, 2)
        self.assertIsNone(parse_listing("2 комнаты\n3 комнаты").rooms)

    def test_new_repair_does_not_mean_new_building_or_empty(self):
        listing = parse_listing("Свежий ремонт, первая сдача, новая мебель, 2 комнаты")
        self.assertIsNone(listing.is_new_building)
        self.assertIsNone(listing.previously_occupied)
        self.assertIsNone(listing.commissioned_year)

    def test_no_residents_after_repair_is_not_first_occupancy(self):
        self.assertIsNone(parse_listing("После ремонта никто не жил").previously_occupied)
        self.assertIsNone(parse_listing("Никто не жил после капитального ремонта").previously_occupied)

    def test_owner_lived_even_when_never_rented(self):
        self.assertTrue(parse_listing("Никогда не сдавалась, жили собственники").previously_occupied)
        self.assertTrue(parse_listing("Не первый заезд").previously_occupied)

    def test_conflicting_occupancy_is_unknown(self):
        self.assertIsNone(parse_listing("Никто не жил. Ранее жили собственники").previously_occupied)

    def test_no_invented_walk_from_advert(self):
        self.assertIsNone(parse_listing("10 минут пешком до метро, 20 минут до офиса").walking_minutes)

    def test_total_area_preferred_over_kitchen(self):
        self.assertEqual(parse_listing("Общая площадь: 55 м², кухня: 12 м²").area_m2, 55)
        self.assertIsNone(parse_listing("Жилая площадь: 28 м²\nКухня 12 м²").area_m2)

    def test_sale_unavailable_and_wanted(self):
        for text in ("Продажа квартиры 2 комнаты", "Квартира сдана. Аренда", "Сниму квартиру в аренду", "Сдано\nАренда", "Неактуально\nАренда", "Объявление снято. Аренда"):
            with self.subTest(text=text):
                self.assertFalse(parse_listing(text).is_rental)

    def test_commissioned_building_not_confused_with_unavailable_rental(self):
        listing = parse_listing("Аренда. Дом сдан 2025. Никто не жил")
        self.assertTrue(listing.is_rental)
        self.assertEqual(listing.commissioned_year, 2025)

    def test_daily_not_longterm(self):
        self.assertFalse(parse_listing("Аренда посуточно").is_long_term)
        self.assertFalse(parse_listing("Аренда посуточно и помесячно").is_long_term)
        self.assertIsNone(parse_listing("Аренда помесячно").is_long_term)
        self.assertIsNone(parse_listing("Аренда квартиры").is_long_term)

    def test_commercial_and_shared_housing_excluded(self):
        for text in ("Сдаётся офис, 2 комнаты, 40 м²", "Аренда коммерческого помещения 40 м²", "Офис в аренду", "Сдаётся комната в квартире", "Аренда комнаты", "Подселение в квартиру"):
            with self.subTest(text=text):
                self.assertFalse(parse_listing(text).is_rental)

    def test_office_destination_not_confused_with_office_rental(self):
        self.assertTrue(parse_listing("Сдаётся квартира, 2 комнаты, 40 м². До офиса 20 минут").is_rental)

    def test_yandex_marker_coordinate_order(self):
        listing = parse_listing("https://yandex.uz/maps/?pt=69.259668,41.296031&z=17")
        self.assertEqual((listing.latitude, listing.longitude), (41.296031, 69.259668))

    def test_map_viewport_not_treated_as_property(self):
        self.assertIsNone(parse_listing("https://yandex.uz/maps/?ll=69.259668,41.296031&z=17").latitude)

    def test_invalid_commission_date_is_unknown(self):
        self.assertIsNone(parse_listing("Дом сдан 31.02.2025").commissioned_on)


if __name__ == "__main__":
    unittest.main()
