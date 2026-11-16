from dataclasses import replace
from datetime import date
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from rentbot.config import Settings, load_env
from rentbot.geo import WalkingRouter, apply_catalogue
from rentbot.http import APIError
from rentbot.models import Listing
from rentbot.storage import Store


class GeoTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "locations.json"
        self.store = Store(":memory:")
        self.settings = Settings(1, "", "", 123, office_lat=41.3, office_lon=69.2,
                                 office_location_confirmed=True, ors_api_key="test-only",
                                 locations_file=self.path)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def catalogue(self, **overrides):
        entry = {"aliases": ["ЖК Тестовый корпус 1"], "latitude": 41.31, "longitude": 69.21,
                 "commissioned_on": "2025-01-01", "source": "https://example.com", "confirmed": True}
        entry.update(overrides)
        self.path.write_text(json.dumps([entry]), encoding="utf-8")

    def test_unconfirmed_catalogue_is_not_evidence(self):
        self.catalogue(confirmed=False)
        listing = Listing("ЖК Тестовый корпус 1")
        apply_catalogue(listing, self.path)
        self.assertIsNone(listing.latitude)
        self.assertIsNone(listing.commissioned_on)

    def test_alias_boundary_does_not_match_another_building(self):
        self.catalogue()
        listing = Listing("ЖК Тестовый корпус 12")
        apply_catalogue(listing, self.path)
        self.assertIsNone(listing.latitude)

    def test_catalogue_date_conflict_not_silently_overridden(self):
        self.catalogue()
        listing = Listing("ЖК Тестовый корпус 1", commissioned_year=2010)
        apply_catalogue(listing, self.path)
        self.assertIsNone(listing.commissioned_on)
        self.assertIsNone(listing.commissioned_year)
        self.assertTrue(listing.warnings)

    def test_landmark_is_not_the_property_address(self):
        self.catalogue()
        for text in ("Ориентир: ЖК Тестовый корпус 1", "Рядом с ЖК Тестовый корпус 1"):
            listing = Listing(text)
            apply_catalogue(listing, self.path)
            self.assertIsNone(listing.latitude)

    async def test_route_uses_foot_profile_lon_lat_order_and_cache(self):
        listing = Listing("", latitude=41.31, longitude=69.21)
        response = {"routes": [{"summary": {"duration": 1200}}]}
        with patch("rentbot.geo.post_json", new=AsyncMock(return_value=response)) as api:
            router = WalkingRouter(self.settings, self.store)
            await router.enrich(listing)
            await router.enrich(listing)
            api.assert_awaited_once()
            self.assertEqual(api.call_args.args[0], "https://api.heigit.org/openrouteservice/v2/directions/foot-walking/json")
            self.assertEqual(api.call_args.kwargs["headers"], {"Authorization": "test-only"})
            self.assertEqual(api.call_args.args[1]["coordinates"], [[69.21, 41.31], [69.2, 41.3]])
            self.assertEqual(listing.walking_minutes, 20)

    async def test_router_failure_is_unknown(self):
        listing = Listing("", latitude=41.31, longitude=69.21)
        with patch("rentbot.geo.post_json", new=AsyncMock(side_effect=APIError("ORS", 429))):
            await WalkingRouter(self.settings, self.store).enrich(listing)
        self.assertIsNone(listing.walking_minutes)

    async def test_no_confirmed_office_does_not_call_route_service(self):
        listing = Listing("", latitude=41.31, longitude=69.21)
        with patch("rentbot.geo.post_json", new=AsyncMock()) as api:
            await WalkingRouter(replace(self.settings, office_location_confirmed=False), self.store).enrich(listing)
            api.assert_not_awaited()
        self.assertIsNone(listing.walking_minutes)


class ConfigTests(unittest.TestCase):
    def test_env_does_not_override_existing_environment_or_execute_values(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"DATA_DIR": "existing"}, clear=True):
            path = Path(directory) / ".env"
            path.write_text("DATA_DIR=changed\nORS_API_KEY='$(not-executed)'\n", encoding="utf-8")
            load_env(path)
            self.assertEqual(os.environ["DATA_DIR"], "existing")
            self.assertEqual(os.environ["ORS_API_KEY"], "$(not-executed)")

    def test_negative_chat_id_and_nan_coordinate_rejected(self):
        settings = Settings(1, "a" * 32, "123:" + "x" * 30, -123,
                            office_lat=float("nan"), office_lon=69.2)
        errors = settings.validate()
        self.assertTrue(any("TELEGRAM_CHAT_ID" in error for error in errors))
        self.assertTrue(any("OFFICE_LAT" in error for error in errors))
        self.assertNotIn("x" * 30, repr(settings))


if __name__ == "__main__":
    unittest.main()
