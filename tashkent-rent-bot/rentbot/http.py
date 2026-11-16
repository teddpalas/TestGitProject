"""Small HTTPS JSON adapter with sanitized failures (tokens live in URLs)."""

import asyncio
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class APIError(Exception):
    def __init__(self, service: str, status: int = 0, retry_after: int = 0):
        self.status = status
        self.retry_after = retry_after
        super().__init__(f"{service}: HTTP {status}" if status else f"{service}: соединение недоступно")


def _post(url: str, body: dict, headers: dict, timeout: int, service: str) -> dict:
    request = Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                      headers={"Content-Type": "application/json", "User-Agent": "tashkent-rent-bot/0.1", **headers})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read(4_000_000))
    except HTTPError as exc:
        retry = 0
        try:
            retry = int(json.loads(exc.read(16_384)).get("parameters", {}).get("retry_after", 0))
        except (ValueError, TypeError, AttributeError):
            pass
        raise APIError(service, exc.code, retry) from None
    except (URLError, OSError, ValueError):
        raise APIError(service) from None


async def post_json(url: str, body: dict, *, headers=None, timeout=30, service="API") -> dict:
    return await asyncio.to_thread(_post, url, body, headers or {}, timeout, service)
