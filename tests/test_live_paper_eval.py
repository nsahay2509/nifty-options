from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.run_research import evaluate_completed_candles
from scripts.schema import Candle, MarketInstrument


TZ = ZoneInfo("Asia/Kolkata")
INDEX = MarketInstrument(name="NIFTY_50_INDEX", exchange_segment="IDX_I", security_id="13", instrument_type="INDEX")
FUT = MarketInstrument(name="NIFTY_CURRENT_MONTH_FUT", exchange_segment="NSE_FNO", security_id="66691", instrument_type="FUTURES")


def make_candle(instrument: MarketInstrument, minute: int, close: float, high: float, low: float) -> Candle:
    start = datetime(2026, 4, 6, 10, minute, tzinfo=TZ)
    return Candle(
        instrument=instrument,
        interval_min=1,
        start=start,
        end=start.replace(minute=start.minute + 1),
        open=close - 10,
        high=high,
        low=low,
        close=close,
        volume=1000,
        tick_count=10,
    )


def test_evaluate_completed_candles_returns_trade_evaluation() -> None:
    prior_day = [make_candle(INDEX, 0, 22500, 22520, 22480)]
    session_candles = [
        make_candle(INDEX, 0, 22520, 22530, 22500),
        make_candle(INDEX, 1, 22545, 22560, 22510),
        make_candle(INDEX, 2, 22610, 22620, 22540),
    ]
    futures_candles = [make_candle(FUT, 2, 22640, 22650, 22580)]

    result = evaluate_completed_candles(
        session_candles=session_candles,
        futures_candles=futures_candles,
        prior_day_candles=prior_day,
    )

    assert result is not None
    assert result.state_assessment.tradeable is True
    assert result.structure_proposal.structure_type != "no_trade"
