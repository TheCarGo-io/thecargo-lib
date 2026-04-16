import os
from datetime import datetime
from zoneinfo import ZoneInfo


def _get_tz() -> ZoneInfo:
    return ZoneInfo(os.environ.get("TIMEZONE", "America/New_York"))


def now_ny() -> datetime:
    return datetime.now(_get_tz())
