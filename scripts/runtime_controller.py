"""Runtime lifecycle control for market-hours-aware websocket and strategy execution."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Awaitable, Callable

from scripts.log import get_logger
from scripts.market_calendar import MarketCalendar


class RuntimeAction(StrEnum):
    """High-level action the runtime should take right now."""

    RUN = "run"
    WAIT = "wait"
    STOP = "stop"
    SKIP = "skip"


@dataclass(frozen=True)
class RuntimeDecision:
    """Represents the controller's current run or stop decision."""

    action: RuntimeAction
    should_run: bool
    reason: str
    phase: str
    trading_day: date
    session_open: datetime
    session_close: datetime
    next_check_at: datetime
    tags: tuple[str, ...]


class RuntimeController:
    """Keeps market-connected tasks aligned with trading-day and session rules."""

    def __init__(
        self,
        *,
        calendar: MarketCalendar | None = None,
        allow_off_hours: bool = False,
    ) -> None:
        self.calendar = calendar or MarketCalendar()
        self.allow_off_hours = allow_off_hours
        self.logger = get_logger("runtime_controller")

    def evaluate(self, now: datetime | None = None) -> RuntimeDecision:
        """Decide whether the runtime should start, wait, stop, or skip."""
        market_now = self.calendar.as_market_datetime(now)
        day_context = self.calendar.describe_day(market_now)
        phase = self.calendar.classify_timestamp(market_now)
        session_window = day_context.session_window

        if not day_context.is_trading_day and not self.allow_off_hours:
            return RuntimeDecision(
                action=RuntimeAction.SKIP,
                should_run=False,
                reason="market_closed_day",
                phase=phase,
                trading_day=market_now.date(),
                session_open=session_window.opens_at,
                session_close=session_window.closes_at,
                next_check_at=session_window.opens_at,
                tags=day_context.tags,
            )

        if phase == "pre_open" and not self.allow_off_hours:
            return RuntimeDecision(
                action=RuntimeAction.WAIT,
                should_run=False,
                reason="pre_open",
                phase=phase,
                trading_day=market_now.date(),
                session_open=session_window.opens_at,
                session_close=session_window.closes_at,
                next_check_at=session_window.opens_at,
                tags=day_context.tags,
            )

        if phase == "open" or self.allow_off_hours:
            return RuntimeDecision(
                action=RuntimeAction.RUN,
                should_run=True,
                reason="session_live" if phase == "open" else "forced_run",
                phase=phase,
                trading_day=market_now.date(),
                session_open=session_window.opens_at,
                session_close=session_window.closes_at,
                next_check_at=session_window.closes_at,
                tags=day_context.tags,
            )

        next_open_day = self.calendar.next_trading_day(market_now.date())
        next_window = self.calendar.session_window(next_open_day)
        return RuntimeDecision(
            action=RuntimeAction.STOP,
            should_run=False,
            reason="session_closed",
            phase=phase,
            trading_day=market_now.date(),
            session_open=session_window.opens_at,
            session_close=session_window.closes_at,
            next_check_at=next_window.opens_at,
            tags=day_context.tags,
        )

    def log_decision(self, decision: RuntimeDecision) -> None:
        """Emit a structured lifecycle log entry for the current decision."""
        self.logger.info(
            "RUNTIME_DECISION | action=%s reason=%s phase=%s should_run=%s trading_day=%s next_check_at=%s tags=%s",
            decision.action.value,
            decision.reason,
            decision.phase,
            decision.should_run,
            decision.trading_day.isoformat(),
            decision.next_check_at.isoformat(),
            ",".join(decision.tags),
        )

    async def run_session(
        self,
        runner: Callable[[], Awaitable[Any]],
        *,
        label: str = "runtime_task",
        now: datetime | None = None,
    ) -> RuntimeDecision:
        """Run a session-scoped task only when the controller allows it."""
        decision = self.evaluate(now)
        self.log_decision(decision)
        if not decision.should_run:
            self.logger.info("RUNTIME_SKIP | label=%s reason=%s", label, decision.reason)
            return decision

        self.logger.info("RUNTIME_START | label=%s trading_day=%s", label, decision.trading_day.isoformat())
        try:
            await runner()
        finally:
            self.logger.info("RUNTIME_STOP | label=%s trading_day=%s", label, decision.trading_day.isoformat())
        return decision

    async def consume_stream(
        self,
        stream,
        on_item: Callable[[Any], Any],
        *,
        item_name: str = "event",
        timestamp_getter: Callable[[Any], datetime] | None = None,
    ) -> int:
        """Consume a websocket or async feed until the session ends or the handler stops it."""
        decision = self.evaluate()
        self.log_decision(decision)
        if not decision.should_run:
            self.logger.info("RUNTIME_SKIP | item=%s reason=%s", item_name, decision.reason)
            return 0

        processed = 0
        self.logger.info("RUNTIME_START | item=%s trading_day=%s", item_name, decision.trading_day.isoformat())
        try:
            async for item in stream:
                evaluation_time = timestamp_getter(item) if timestamp_getter is not None else None
                live_decision = self.evaluate(evaluation_time)
                if not live_decision.should_run:
                    self.logger.info(
                        "RUNTIME_STOP | item=%s reason=%s trading_day=%s",
                        item_name,
                        live_decision.reason,
                        live_decision.trading_day.isoformat(),
                    )
                    break

                handler_result = on_item(item)
                if inspect.isawaitable(handler_result):
                    handler_result = await handler_result
                processed += 1

                if handler_result is False:
                    self.logger.info("RUNTIME_STOP | item=%s reason=handler_requested_stop", item_name)
                    break
        finally:
            self.logger.info("RUNTIME_FLUSH | item=%s processed=%s", item_name, processed)
        return processed
