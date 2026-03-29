from pathlib import Path

from scripts.logger import get_logger
from scripts.paper_trade_engine_core import Position
from scripts.paper_trade_engine_factory import TradeEngineSpec, build_engine_class


logger = get_logger("paper_trade_buy")

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

OPEN_POS_FILE = DATA_DIR / "open_position_buy.json"


SPEC = TradeEngineSpec(
    side="BUY",
    logger=logger,
    open_position_file_getter=lambda: OPEN_POS_FILE,
    pnl_file_getter=lambda: BASE_DIR / "data" / "results" / "system_pnl_buy.csv",
    trade_events_file_getter=lambda: BASE_DIR / "data" / "results" / "trade_events_buy.csv",
    recovery_message="Recovered OPEN buy position from disk",
    recovery_error_code="OPEN_BUY_POSITION_RECOVERY_FAILED",
    stale_position_message="STALE BUY POSITION DETECTED -> FORCE CLOSE",
    stale_position_check_error_code="STALE_BUY_POSITION_CHECK_FAILED",
    reset_message_template="New trading day detected | resetting buy engine state from {old_date} to {new_date}",
    entry_invalid_regime_message="ENTRY_SKIPPED_INVALID_REGIME | {regime}",
)


PaperTradeEngine = build_engine_class(SPEC)


_engine = PaperTradeEngine()


def run(signal=None, regime=None, history=None, ltp_map=None):
    _engine.tick(signal=signal, regime=regime, history=history, ltp_map=ltp_map)
