"""Session data loading helpers for the rebuilt NIFTY runtime."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.config import APP_CONFIG, BASE_DIR
from scripts.market_calendar import MarketCalendar
from scripts.schema import Candle, MarketInstrument


INDEX_INSTRUMENT = MarketInstrument(
    name=APP_CONFIG.market_data.index_instrument.name,
    exchange_segment=APP_CONFIG.market_data.index_instrument.exchange_segment,
    security_id=APP_CONFIG.market_data.index_instrument.security_id,
    instrument_type="INDEX",
)


def load_spot_candles_from_jsonl(
    path: Path,
    *,
    instrument: MarketInstrument | None = None,
) -> list[Candle]:
    """Load archived spot candles from the historical JSONL format."""
    if not path.exists():
        return []

    tz = ZoneInfo(APP_CONFIG.session.market_timezone)
    instrument_ref = instrument or INDEX_INSTRUMENT
    candles: list[Candle] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            payload = json.loads(line)
            start = datetime.strptime(payload["ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
            candles.append(
                Candle(
                    instrument=instrument_ref,
                    interval_min=1,
                    start=start,
                    end=start + timedelta(minutes=1),
                    open=float(payload.get("open", 0.0)),
                    high=float(payload.get("high", 0.0)),
                    low=float(payload.get("low", 0.0)),
                    close=float(payload.get("close", 0.0)),
                    volume=int(payload.get("volume", 0) or 0),
                    tick_count=1,
                )
            )
    return candles


def load_prior_day_index_candles(
    as_of_date,
    *,
    calendar: MarketCalendar | None = None,
    archive_dir: Path | None = None,
) -> list[Candle]:
    """Load previous trading-day NIFTY spot candles from the archive store."""
    market_calendar = calendar or MarketCalendar()
    prior_day = market_calendar.previous_trading_day(as_of_date)
    base_dir = archive_dir or (BASE_DIR / "archive" / "data" / "spot")
    return load_spot_candles_from_jsonl(base_dir / f"{prior_day.isoformat()}.jsonl")
