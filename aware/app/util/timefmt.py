from __future__ import annotations

import logging
from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from aware.app.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=4)
def display_tz() -> ZoneInfo | None:
    tz_name = get_settings().display_timezone.strip()
    if not tz_name:
        return None
    try:
        return ZoneInfo(tz_name)
    except Exception:
        logger.warning("Invalid AWARE_DISPLAY_TIMEZONE: %s", tz_name)
        return None


def format_clock(ts: float) -> str:
    tz = display_tz()
    dt = datetime.fromtimestamp(ts, tz=tz) if tz else datetime.fromtimestamp(ts)
    return dt.strftime("%H:%M:%S")


def format_period(ts_start: float, ts_end: float) -> str:
    tz = display_tz()
    if tz:
        start = datetime.fromtimestamp(ts_start, tz=tz).strftime("%H:%M")
        end = datetime.fromtimestamp(ts_end, tz=tz).strftime("%H:%M")
    else:
        start = datetime.fromtimestamp(ts_start).strftime("%H:%M")
        end = datetime.fromtimestamp(ts_end).strftime("%H:%M")
    return f"{start}–{end}"


def now_in_display_tz() -> datetime:
    tz = display_tz()
    return datetime.now(tz) if tz else datetime.now()
