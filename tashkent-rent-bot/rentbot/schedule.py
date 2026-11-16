"""Delivery times in the user's timezone, independent of the host timezone."""

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    TASHKENT = ZoneInfo("Asia/Tashkent")
except ZoneInfoNotFoundError:
    # Windows may have neither an IANA database nor the optional tzdata package.
    # Tashkent currently observes UTC+5 all year; production installs include tzdata.
    TASHKENT = timezone(timedelta(hours=5), "Asia/Tashkent")


def quiet_due(now: datetime) -> datetime:
    """Return the next quiet delivery time as an aware UTC datetime.

    Before 16:50 on Monday-Friday, queue for 16:50 that same day. At and
    after 16:50, and throughout Saturday/Sunday, deliver immediately.
    Public holidays do not override this explicitly agreed weekly schedule.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")
    local = now.astimezone(TASHKENT)
    if local.weekday() < 5 and local.time() < time(16, 50):
        local = local.replace(hour=16, minute=50, second=0, microsecond=0)
    return local.astimezone(timezone.utc)
