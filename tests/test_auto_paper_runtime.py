from __future__ import annotations

import asyncio
from datetime import date, datetime
from zoneinfo import ZoneInfo

from scripts.auto_paper_runtime import compute_sleep_seconds, supervise_forever


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


def test_supervise_forever_passes_shared_stop_event_to_runner() -> None:
    class _SessionWindow:
        def __init__(self, opens_at: datetime, closes_at: datetime) -> None:
            self.opens_at = opens_at
            self.closes_at = closes_at

    class _DayContext:
        def __init__(self, now: datetime) -> None:
            self.is_trading_day = True
            self.session_window = _SessionWindow(
                now.replace(hour=9, minute=15, second=0, microsecond=0),
                now.replace(hour=15, minute=30, second=0, microsecond=0),
            )
            self.tags = ("trading_day",)

    class _Calendar:
        def __init__(self, now: datetime) -> None:
            self._now = now

        def as_market_datetime(self, now: datetime | None = None) -> datetime:
            return now or self._now

        def describe_day(self, market_now: datetime):
            return _DayContext(market_now)

        def classify_timestamp(self, market_now: datetime | None = None) -> str:
            return "open"

        def next_trading_day(self, current_day: date) -> date:
            return current_day

    async def _run() -> None:
        stop_event = asyncio.Event()
        calls: dict[str, object] = {"count": 0}

        async def runner(*, stop_event: asyncio.Event, install_signal_handlers: bool = True) -> None:
            calls["count"] = int(calls["count"]) + 1
            calls["install_signal_handlers"] = install_signal_handlers
            stop_event.set()

        await supervise_forever(
            runner=runner,
            calendar=_Calendar(datetime(2026, 4, 8, 12, 0, tzinfo=IST)),
            restart_delay_seconds=0.01,
            stop_event=stop_event,
        )

        assert calls["count"] == 1
        assert calls["install_signal_handlers"] is False

    asyncio.run(_run())
