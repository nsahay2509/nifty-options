"""Tick-to-candle aggregation for the rebuilt NIFTY system."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from scripts.log import get_logger
from scripts.schema import Candle, MarketInstrument, MarketTick


def floor_time_to_interval(ts: datetime, interval_min: int) -> datetime:
    """Floor a timestamp to the start of its candle interval."""
    minute = (ts.minute // interval_min) * interval_min
    return ts.replace(minute=minute, second=0, microsecond=0)


@dataclass
class _CandleState:
    instrument: MarketInstrument
    interval_min: int
    start: datetime
    end: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    open_interest: int
    tick_count: int
    last_volume_seen: int

    def to_candle(self) -> Candle:
        return Candle(
            instrument=self.instrument,
            interval_min=self.interval_min,
            start=self.start,
            end=self.end,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=max(self.volume, 0),
            open_interest=self.open_interest,
            tick_count=self.tick_count,
        )


class CandleBuilder:
    """Incrementally aggregates market ticks into candles."""

    def __init__(self, interval_min: int = 1) -> None:
        self.interval_min = interval_min
        self._states: dict[str, _CandleState] = {}
        self.logger = get_logger("candle_builder")

    def update(self, tick: MarketTick) -> list[Candle]:
        """Consume a tick and return any completed candles."""
        key = f"{tick.instrument.exchange_segment}:{tick.instrument.security_id}:{self.interval_min}"
        start = floor_time_to_interval(tick.timestamp, self.interval_min)
        end = start + timedelta(minutes=self.interval_min)
        state = self._states.get(key)

        if state is None:
            self._states[key] = self._create_state(tick, start, end)
            return []

        if start != state.start:
            completed = state.to_candle()
            self._states[key] = self._create_state(tick, start, end)
            return [completed]

        incremental_volume = max(tick.volume - state.last_volume_seen, 0)
        state.high = max(state.high, tick.ltp)
        state.low = min(state.low, tick.ltp)
        state.close = tick.ltp
        state.volume += incremental_volume
        state.open_interest = tick.open_interest
        state.tick_count += 1
        state.last_volume_seen = tick.volume
        return []

    def flush(self) -> list[Candle]:
        """Flush all active candle states into completed candles."""
        candles = [state.to_candle() for state in self._states.values()]
        self._states.clear()
        return candles

    def _create_state(self, tick: MarketTick, start: datetime, end: datetime) -> _CandleState:
        return _CandleState(
            instrument=tick.instrument,
            interval_min=self.interval_min,
            start=start,
            end=end,
            open=tick.ltp,
            high=tick.ltp,
            low=tick.ltp,
            close=tick.ltp,
            volume=max(tick.volume, 0),
            open_interest=tick.open_interest,
            tick_count=1,
            last_volume_seen=tick.volume,
        )
