"""Offline and live-paper evaluation entrypoints for the rebuilt NIFTY runtime."""

from __future__ import annotations

from collections.abc import Sequence

from scripts.log import get_logger
from scripts.market_calendar import MarketCalendar
from scripts.schema import Candle
from scripts.session_features import build_session_snapshot
from scripts.trade_engine import TradeEngine, TradeEvaluation


logger = get_logger("run_research")


def evaluate_completed_candles(
    *,
    session_candles: Sequence[Candle],
    futures_candles: Sequence[Candle] = (),
    prior_day_candles: Sequence[Candle] = (),
) -> TradeEvaluation | None:
    """Run the decision spine on already completed candle inputs."""
    if not session_candles:
        return None

    ordered_index = sorted(session_candles, key=lambda candle: candle.start)
    ordered_futures = sorted(futures_candles, key=lambda candle: candle.start)
    snapshot = build_session_snapshot(
        timestamp=ordered_index[-1].end,
        index_candle=ordered_index[-1],
        futures_candle=ordered_futures[-1] if ordered_futures else None,
        session_candles=ordered_index,
        prior_day_candles=prior_day_candles,
    )
    result = TradeEngine().evaluate(snapshot)
    logger.info(
        "PAPER_EVAL | state=%s playbook=%s structure=%s no_trade=%s",
        result.state_assessment.state_name,
        result.playbook_decision.playbook_name,
        result.structure_proposal.structure_type,
        result.playbook_decision.no_trade,
    )
    return result
