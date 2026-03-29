from pathlib import Path

from scripts.logger import get_logger
from scripts.app_config import APP_CONFIG
from scripts.paper_trade_engine_core import BasePaperTradeEngine, Position


logger = get_logger("paper_trade_buy")

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

OPEN_POS_FILE = DATA_DIR / "open_position_buy.json"


class PaperTradeEngine(BasePaperTradeEngine):
    logger = logger
    recovery_message = "Recovered OPEN buy position from disk"
    recovery_error_code = "OPEN_BUY_POSITION_RECOVERY_FAILED"
    stale_position_message = "STALE BUY POSITION DETECTED -> FORCE CLOSE"
    stale_position_check_error_code = "STALE_BUY_POSITION_CHECK_FAILED"
    entry_invalid_regime_message = "ENTRY_SKIPPED_INVALID_REGIME | {regime}"

    def get_open_position_file(self) -> Path:
        return OPEN_POS_FILE

    def get_pnl_file(self) -> Path:
        return BASE_DIR / "data" / "results" / "system_pnl_buy.csv"

    def get_trade_events_file(self) -> Path:
        return BASE_DIR / "data" / "results" / "trade_events_buy.csv"

    def get_side(self) -> str:
        return "BUY"

    def get_reset_log_message(self, old_date, new_date) -> str:
        return f"New trading day detected | resetting buy engine state from {old_date} to {new_date}"

    def resolve_entry_ids(self, regime: str, atm: dict) -> tuple[int | None, int | None]:
        if regime == "SELL_PE":
            return atm["ce_security_id"], None
        return None, atm["pe_security_id"]

    def format_entry_message(
        self,
        regime: str,
        spot: float,
        atm: dict,
        ce_id: int | None,
        pe_id: int | None,
    ) -> str:
        return (
            f"ENTRY | BUY_FROM_{regime} | spot={spot:.2f} "
            f"strike={atm['strike']} exp={atm['expiry']} "
            f"ce_id={ce_id} pe_id={pe_id} lots={APP_CONFIG.trade.lots}"
        )

    def compute_leg_pnl(self, entry: float, ltp: float, qty: int) -> float:
        return (ltp - entry) * qty


_engine = PaperTradeEngine()


def run(signal=None, regime=None, history=None, ltp_map=None):
    _engine.tick(signal=signal, regime=regime, history=history, ltp_map=ltp_map)
