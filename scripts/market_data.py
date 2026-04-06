"""Market-data orchestration around index and futures base streams."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from scripts.config import APP_CONFIG
from scripts.log import get_logger
from scripts.schema import Candle, MarketInstrument, MarketTick

from .candle_builder import CandleBuilder


@dataclass(frozen=True)
class BaseSubscriptions:
    """Represents the base live subscriptions used by the system."""

    index: MarketInstrument
    futures: MarketInstrument


class TickStore:
    """Appends normalized ticks to JSONL files for later replay and debugging."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or APP_CONFIG.market_data.tick_store_dir
        self.logger = get_logger("market_data.tick_store")

    def append(self, tick: MarketTick) -> None:
        session_date = tick.timestamp.strftime("%Y-%m-%d")
        target = self.base_dir / session_date / f"{tick.instrument.name}.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": tick.timestamp.isoformat(),
            "instrument": tick.instrument.name,
            "exchange_segment": tick.instrument.exchange_segment,
            "security_id": tick.instrument.security_id,
            "ltp": tick.ltp,
            "ltq": tick.ltq,
            "volume": tick.volume,
            "open_interest": tick.open_interest,
            "day_open": tick.day_open,
            "day_high": tick.day_high,
            "day_low": tick.day_low,
        }
        with target.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")


class CandleStore:
    """Persists completed candles to JSONL files."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or APP_CONFIG.market_data.candle_store_dir
        self.logger = get_logger("market_data.candle_store")

    def append(self, candle: Candle) -> None:
        session_date = candle.start.strftime("%Y-%m-%d")
        target = self.base_dir / session_date / f"{candle.instrument.name}_{candle.interval_min}m.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "start": candle.start.isoformat(),
            "end": candle.end.isoformat(),
            "instrument": candle.instrument.name,
            "interval_min": candle.interval_min,
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
            "open_interest": candle.open_interest,
            "tick_count": candle.tick_count,
        }
        with target.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")


class MarketDataService:
    """Coordinates normalized ticks, tick storage, and candle aggregation."""

    def __init__(self) -> None:
        self.logger = get_logger("market_data")
        self.tick_store = TickStore()
        self.candle_store = CandleStore()
        self.builders = {
            interval: CandleBuilder(interval)
            for interval in APP_CONFIG.market_data.derive_intervals_min
        }

    def handle_tick(self, tick: MarketTick) -> list[Candle]:
        """Store a normalized tick and return any completed candles."""
        self.tick_store.append(tick)
        completed: list[Candle] = []
        for builder in self.builders.values():
            candles = builder.update(tick)
            for candle in candles:
                self.candle_store.append(candle)
                completed.append(candle)
        return completed


def build_base_subscriptions() -> BaseSubscriptions:
    """Build the default base instrument subscriptions for the system."""
    index = MarketInstrument(
        name=APP_CONFIG.market_data.index_instrument.name,
        exchange_segment=APP_CONFIG.market_data.index_instrument.exchange_segment,
        security_id=APP_CONFIG.market_data.index_instrument.security_id,
        instrument_type="INDEX",
    )
    futures = MarketInstrument(
        name=APP_CONFIG.market_data.futures_instrument.name,
        exchange_segment=APP_CONFIG.market_data.futures_instrument.exchange_segment,
        security_id=APP_CONFIG.market_data.futures_instrument.security_id,
        instrument_type="FUTURES",
    )
    return BaseSubscriptions(index=index, futures=futures)
