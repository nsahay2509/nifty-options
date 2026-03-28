from pathlib import Path

from scripts.logger import get_logger
from scripts.paper_trade_engine_core import BasePaperTradeEngine, IST, LOTS, Position


logger = get_logger("paper_trade")

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

OPEN_POS_FILE = DATA_DIR / "open_position.json"


class PaperTradeEngine(BasePaperTradeEngine):
    logger = logger
    recovery_message = "Recovered OPEN position from disk"
    recovery_error_code = "OPEN_POSITION_RECOVERY_FAILED"
    stale_position_message = "STALE POSITION DETECTED -> FORCE CLOSE"
    stale_position_check_error_code = "STALE_POSITION_CHECK_FAILED"

    def get_open_position_file(self) -> Path:
        return OPEN_POS_FILE

    def get_pnl_file(self) -> Path:
        return BASE_DIR / "data" / "results" / "system_pnl.csv"

    def get_trade_events_file(self) -> Path:
        return BASE_DIR / "data" / "results" / "trade_events_sell.csv"

    def get_side(self) -> str:
        return "SELL"

    def get_reset_log_message(self, old_date, new_date) -> str:
        return f"New trading day detected | resetting engine state from {old_date} to {new_date}"

    def resolve_entry_ids(self, regime: str, atm: dict) -> tuple[int | None, int | None]:
        ce_id = None
        pe_id = None

        if regime == "SELL_PE":
            pe_id = atm["pe_security_id"]
        elif regime == "SELL_CE":
            ce_id = atm["ce_security_id"]

        return ce_id, pe_id

    def format_entry_message(
        self,
        regime: str,
        spot: float,
        atm: dict,
        ce_id: int | None,
        pe_id: int | None,
    ) -> str:
        return (
            f"ENTRY | {regime} | spot={spot:.2f} "
            f"strike={atm['strike']} exp={atm['expiry']} "
            f"ce_id={ce_id} pe_id={pe_id} lots={LOTS}"
        )

    def compute_leg_pnl(self, entry: float, ltp: float, qty: int) -> float:
        return (entry - ltp) * qty


_engine = PaperTradeEngine()


def run(signal=None, regime=None, history=None, ltp_map=None):
    _engine.tick(signal=signal, regime=regime, history=history, ltp_map=ltp_map)
