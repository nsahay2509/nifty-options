import subprocess
import sys
from pathlib import Path

from scripts.app_config import APP_CONFIG
from scripts.clock import get_clock
from scripts.logger import get_logger
from scripts.models import OpenPosition
from scripts.option_resolver import get_atm_straddle
from scripts.paper_mtm_engine import run as run_mtm
from scripts.paper_mtm_engine_buy import run as run_buy_mtm
from scripts.paper_trade_engine import run as run_paper_trade
from scripts.paper_trade_engine_buy import run as run_buy_trade
from scripts.regime_classifier import load_last_candles
from scripts.signal_engine import generate_signal
from scripts.state_utils import safe_load_json
from scripts.utils import ensure_complete_ltp_map


BASE_DIR = Path(__file__).resolve().parents[1]
logger = get_logger("evaluator")


def run_updater():
    try:
        result = subprocess.run(
            [sys.executable, "-m", "scripts.update_nifty_spot"],
            cwd=BASE_DIR,
        )

        if result.returncode != 0:
            logger.error("UPDATE FAILED")
            return False

        return True
    except Exception as exc:
        logger.exception(f"Updater crashed: {exc}")
        return False


def collect_open_position_security_ids(position_file: Path, label: str) -> list[int]:
    position_data = safe_load_json(position_file, None)
    if not position_data:
        return []

    if position_data.get("status") != "OPEN":
        return []

    security_ids: list[int] = []
    for leg in position_data.get("legs", []):
        try:
            security_ids.append(int(leg.get("security_id")))
        except (TypeError, ValueError):
            logger.warning(
                f"{label}_POSITION_INVALID_SECURITY_ID | file={position_file.name} leg={leg}"
            )

    return security_ids


def collect_regime_security_ids(regime, history, resolver=None) -> list[int]:
    if regime not in ("SELL_PE", "SELL_CE"):
        return []

    if not history:
        logger.warning("REGIME_SECURITY_COLLECTION_SKIPPED | history_empty")
        return []

    try:
        last_candle = history[-1]
        spot = float(last_candle["close"])
        option_resolver = resolver or get_atm_straddle
        atm = option_resolver(spot)
    except Exception as exc:
        logger.exception(f"REGIME_SECURITY_COLLECTION_FAILED | regime={regime} error={exc}")
        return []

    if regime == "SELL_PE":
        return [atm["pe_security_id"], atm["ce_security_id"]]

    return [atm["ce_security_id"], atm["pe_security_id"]]


def build_cycle_context(clock=None):
    active_clock = clock or get_clock()
    history = load_last_candles(APP_CONFIG.regime.window, clock=active_clock)
    signal, regime = generate_signal(history, clock=active_clock)

    security_ids: list[int] = []
    security_ids.extend(
        collect_open_position_security_ids(BASE_DIR / "data" / "open_position.json", "SELL")
    )
    security_ids.extend(
        collect_open_position_security_ids(BASE_DIR / "data" / "open_position_buy.json", "BUY")
    )
    security_ids.extend(collect_regime_security_ids(regime, history))
    security_ids = list(set(security_ids))

    ltp_map = {}
    if security_ids:
        ltp_map, complete = ensure_complete_ltp_map(
            security_ids,
            logger=logger,
        )
        if not complete:
            logger.warning(f"EVALUATOR_LTP_INCOMPLETE | ids={security_ids} map={ltp_map}")

    return {
        "history": history,
        "signal": signal,
        "regime": regime,
        "ltp_map": ltp_map,
    }


def run_cycle(clock=None):
    active_clock = clock or get_clock()

    logger.info("")
    logger.info("-" * 60)
    logger.info("CYCLE START")
    logger.info("-" * 60)

    logger.info("STEP 1: updater start")
    ok = run_updater()
    logger.info(f"STEP 1: updater end | ok={ok}")

    if ok:
        context = build_cycle_context(clock=active_clock)
        history = context["history"]
        signal = context["signal"]
        regime = context["regime"]
        ltp_map = context["ltp_map"]

        logger.info(f"MASTER_SIGNAL | signal={signal} regime={regime}")
        logger.info(f"LTP_MAP_CYCLE | {ltp_map}")

        logger.info("STEP 2: SELL paper_trade start")
        run_paper_trade(signal=signal, regime=regime, history=history, ltp_map=ltp_map)
        logger.info("STEP 2: SELL paper_trade end")

        logger.info("STEP 3: SELL mtm start")
        run_mtm(ltp_map=ltp_map, clock=active_clock)
        logger.info("STEP 3: SELL mtm end")

        logger.info("STEP 4: BUY paper_trade start")
        run_buy_trade(signal=signal, regime=regime, history=history, ltp_map=ltp_map)
        logger.info("STEP 4: BUY paper_trade end")

        logger.info("STEP 5: BUY mtm start")
        run_buy_mtm(ltp_map=ltp_map, clock=active_clock)
        logger.info("STEP 5: BUY mtm end")

    logger.info("-" * 60)
    logger.info("CYCLE END")
    logger.info("-" * 60)
    logger.info("")
