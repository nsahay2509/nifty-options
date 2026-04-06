from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from scripts.market_calendar import MarketCalendar
from scripts.runtime_controller import RuntimeAction, RuntimeController


def test_runtime_controller_waits_before_open() -> None:
    controller = RuntimeController(calendar=MarketCalendar())
    now = datetime(2026, 4, 9, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

    decision = controller.evaluate(now)

    assert decision.action == RuntimeAction.WAIT
    assert decision.should_run is False
    assert decision.reason == "pre_open"


def test_runtime_controller_runs_during_session() -> None:
    controller = RuntimeController(calendar=MarketCalendar())
    now = datetime(2026, 4, 9, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

    decision = controller.evaluate(now)

    assert decision.action == RuntimeAction.RUN
    assert decision.should_run is True
    assert decision.trading_day == date(2026, 4, 9)


def test_runtime_controller_skips_holidays() -> None:
    controller = RuntimeController(calendar=MarketCalendar(holidays={date(2026, 4, 10): "Mock Holiday"}))
    now = datetime(2026, 4, 10, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

    decision = controller.evaluate(now)

    assert decision.action == RuntimeAction.SKIP
    assert decision.should_run is False
    assert decision.reason == "market_closed_day"
    assert decision.next_check_at.date() == date(2026, 4, 13)
