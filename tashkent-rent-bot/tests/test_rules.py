import unittest
from dataclasses import replace
from datetime import date

from rentbot.models import Listing
from rentbot.rules import classify


TODAY = date(2026, 11, 15)


def suitable(**kwargs):
    listing = Listing(text="fixture", rooms=2, area_m2=40, price_usd=800,
                      commissioned_on=date(2025, 1, 1), previously_occupied=False,
                      is_new_building=True, is_rental=True, is_long_term=True,
                      walking_minutes=20)
    return replace(listing, **kwargs)


class RulesTests(unittest.TestCase):
    def test_exact_boundaries_loud(self):
        self.assertEqual(classify(suitable(), TODAY).tier, "loud")

    def test_hard_exclusions(self):
        for data in ({"rooms": 1}, {"area_m2": 39.99}, {"price_usd": 850.01},
                     {"walking_minutes": 25.001}, {"is_rental": False},
                     {"is_long_term": False}, {"is_new_building": False}):
            with self.subTest(data=data):
                self.assertEqual(classify(suitable(**data), TODAY).tier, "reject")

    def test_each_single_deviation_is_quiet(self):
        for data in ({"price_usd": 850}, {"walking_minutes": 25}, {"previously_occupied": True}):
            with self.subTest(data=data):
                self.assertEqual(classify(suitable(**data), TODAY).tier, "quiet")

    def test_two_deviations_rejected(self):
        self.assertEqual(classify(suitable(price_usd=850, previously_occupied=True), TODAY).tier, "reject")
        self.assertEqual(classify(suitable(price_usd=850, walking_minutes=25), TODAY).tier, "reject")

    def test_calendar_three_year_boundary(self):
        self.assertEqual(classify(suitable(commissioned_on=date(2023, 11, 15)), TODAY).tier, "loud")
        self.assertEqual(classify(suitable(commissioned_on=date(2023, 11, 14)), TODAY).tier, "reject")
        self.assertEqual(classify(suitable(commissioned_on=date(2027, 1, 1)), TODAY).tier, "reject")

    def test_leap_day_calendar_age(self):
        self.assertEqual(classify(suitable(commissioned_on=date(2021, 2, 28)), date(2024, 2, 29)).tier, "loud")

    def test_year_only_conservative(self):
        self.assertEqual(classify(suitable(commissioned_on=None, commissioned_year=2023), TODAY).tier, "quiet")
        self.assertEqual(classify(suitable(commissioned_on=None, commissioned_year=2024), TODAY).tier, "loud")
        self.assertEqual(classify(suitable(commissioned_on=None, commissioned_year=2022), TODAY).tier, "reject")
        self.assertEqual(classify(suitable(commissioned_on=None, commissioned_year=2027), TODAY).tier, "reject")

    def test_one_or_two_missing_values_quiet(self):
        self.assertEqual(classify(suitable(area_m2=None), TODAY).tier, "quiet")
        self.assertEqual(classify(suitable(area_m2=None, walking_minutes=None), TODAY).tier, "quiet")

    def test_three_missing_values_rejected(self):
        self.assertEqual(classify(suitable(area_m2=None, walking_minutes=None, previously_occupied=None), TODAY).tier, "reject")

    def test_unknown_and_deviation_rejected(self):
        self.assertEqual(classify(suitable(area_m2=None, price_usd=825), TODAY).tier, "reject")

    def test_unconfirmed_long_term_cannot_be_loud(self):
        self.assertEqual(classify(suitable(is_long_term=None), TODAY).tier, "quiet")

    def test_not_a_rental_must_not_pass(self):
        self.assertEqual(classify(suitable(is_rental=None), TODAY).tier, "reject")

    def test_nonfinite_values_rejected(self):
        for field in ("area_m2", "price_usd", "walking_minutes"):
            for value in (float("nan"), float("inf"), 0, -1):
                with self.subTest(field=field, value=value):
                    self.assertEqual(classify(suitable(**{field: value}), TODAY).tier, "reject")

    def test_building_age_not_inferred_from_newbuild_label(self):
        self.assertEqual(classify(suitable(commissioned_on=None), TODAY).tier, "quiet")


if __name__ == "__main__":
    unittest.main()
