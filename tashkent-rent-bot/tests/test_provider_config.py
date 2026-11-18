from dataclasses import replace
import os
import unittest
from unittest.mock import patch

from rentbot.config import Settings
from rentbot.models import Decision, Listing
from rentbot.pipeline import explain


class ProviderConfigTests(unittest.TestCase):
    def test_legacy_configuration_stays_on_ors(self):
        with patch.dict(os.environ, {"ORS_API_KEY": "ors-test"}, clear=True):
            config = Settings.from_env()
            self.assertEqual(config.routing_provider, "ors")
            self.assertEqual(config.routing_key, "ors-test")

    def test_geoapify_requires_its_own_key(self):
        config = Settings(1, "", "", 1, ors_api_key="ors-test", routing_provider="geoapify")
        self.assertEqual(config.routing_key, "")
        config = replace(config, geoapify_api_key="geoapify-secret")
        self.assertEqual(config.routing_key, "geoapify-secret")
        self.assertNotIn("geoapify-secret", repr(config))

    def test_unknown_provider_is_invalid(self):
        config = Settings(1, "", "", 1, routing_provider="drive")
        self.assertTrue(any("ROUTING_PROVIDER" in error for error in config.validate()))

    def test_geoapify_attribution_in_card(self):
        listing = Listing("", walking_minutes=10, evidence={"walking_provider": "geoapify"})
        text = explain(listing, Decision("quiet"), "https://t.me/example/1")
        self.assertIn("https://www.geoapify.com/", text)
        self.assertIn("https://www.openstreetmap.org/copyright", text)
        self.assertNotIn("apiKey", text)


if __name__ == "__main__":
    unittest.main()
