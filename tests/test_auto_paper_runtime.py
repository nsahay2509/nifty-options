from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.auto_paper_runtime import compute_sleep_seconds


IST = ZoneInfo("Asia/Kolkata")


def test_compute_sleep_seconds_caps_long_waits() -> None:
    now = datetime(2026, 4, 6, 15, 45, tzinfo=IST)
    next_check_at = datetime(2026, 4, 7, 9, 15, tzinfo=IST)

    sleep_seconds = compute_sleep_seconds(next_check_at, now, max_sleep_seconds=300.0)

    assert sleep_seconds == 300.0


def test_compute_sleep_seconds_uses_exact_short_wait() -> None:
    now = datetime(2026, 4, 7, 9, 14, 30, tzinfo=IST)
    next_check_at = datetime(2026, 4, 7, 9, 15, tzinfo=IST)

    sleep_seconds = compute_sleep_seconds(next_check_at, now, max_sleep_seconds=300.0)

    assert sleep_seconds == 30.0
