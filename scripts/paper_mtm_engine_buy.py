from pathlib import Path

from scripts.logger import get_logger
from scripts.paper_mtm_engine_core import MtmConfig, run as run_mtm_core

logger = get_logger("paper_mtm_buy")

BASE_DIR = Path(__file__).resolve().parents[1]

CONFIG = MtmConfig(
    open_position_file=BASE_DIR / "data" / "open_position_buy.json",
    results_file=BASE_DIR / "data" / "results" / "system_pnl_buy.csv",
    last_state_file=BASE_DIR / "data" / "last_state_buy.json",
    pnl_state_file=BASE_DIR / "data" / "pnl_state_buy.json",
    side="BUY",
    logger=logger,
    missing_ltp_error_code="LTP_MISSING",
)

def run(ltp_map=None, clock=None):
    run_mtm_core(CONFIG, ltp_map=ltp_map, clock=clock)
