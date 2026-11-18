import io
import json
import traceback
import unittest
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from rentbot.http import APIError, get_json


class HTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_encodes_parameters_without_changing_coordinate_order(self):
        response = io.BytesIO(json.dumps({"features": []}).encode())
        with patch("rentbot.http.urlopen", return_value=response) as request:
            await get_json("https://api.geoapify.com/v1/routing",
                           {"waypoints": "41.31,69.21|41.3,69.2", "mode": "walk", "apiKey": "test-secret"})
            sent = request.call_args.args[0]
            self.assertEqual(sent.get_method(), "GET")
            query = parse_qs(urlsplit(sent.full_url).query)
            self.assertEqual(query["waypoints"], ["41.31,69.21|41.3,69.2"])
            self.assertEqual(query["mode"], ["walk"])

    async def test_http_failure_does_not_expose_key_or_url(self):
        secret = "fake-sensitive-value"
        url = "https://api.geoapify.com/v1/routing?apiKey=" + secret
        error = HTTPError(url, 429, "Request with " + secret, {"Retry-After": "15"},
                          io.BytesIO(secret.encode()))
        with patch("rentbot.http.urlopen", side_effect=error):
            try:
                await get_json("https://api.geoapify.com/v1/routing", {"apiKey": secret}, service="Geoapify")
            except APIError as sanitized:
                self.assertEqual(sanitized.status, 429)
                self.assertEqual(sanitized.retry_after, 15)
                self.assertNotIn(secret, str(sanitized))
                self.assertNotIn(secret, "".join(traceback.format_exception(sanitized)))
            else:
                self.fail("Expected sanitized failure")

    async def test_network_error_is_sanitized(self):
        with patch("rentbot.http.urlopen", side_effect=URLError("https://example.com/?apiKey=test-secret")):
            with self.assertRaises(APIError) as raised:
                await get_json("https://example.com", {"apiKey": "test-secret"})
            self.assertNotIn("test-secret", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
