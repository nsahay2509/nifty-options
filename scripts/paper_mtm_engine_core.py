from dataclasses import dataclass
from pathlib import Path

from scripts.app_config import APP_CONFIG
from scripts.clock import get_clock
from scripts.state_utils import atomic_write_json, safe_load_json
from scripts.utils import ensure_complete_ltp_map


@dataclass(frozen=True)
class MtmConfig:
    open_position_file: Path
    results_file: Path
    last_state_file: Path
    pnl_state_file: Path
    side: str
    logger: object
    missing_ltp_error_code: str
    log_shared_ltp_map: bool = False


def _safe_load_json(path: Path, default):
    return safe_load_json(path, default)


def load_last_state(config: MtmConfig):
    return _safe_load_json(config.last_state_file, {})


def save_last_state(config: MtmConfig, state: dict):
    atomic_write_json(config.last_state_file, state)


def load_realised(config: MtmConfig, clock=None) -> float:
    data = _safe_load_json(config.pnl_state_file, {})

    active_clock = clock or get_clock()
    today = active_clock.today().strftime("%Y-%m-%d")
    saved_date = data.get("date")

    if saved_date != today:
        return 0.0

    return float(data.get("realised_today", 0.0))


def save_realised(config: MtmConfig, val: float, clock=None):
    active_clock = clock or get_clock()
    today = active_clock.today().strftime("%Y-%m-%d")

    atomic_write_json(config.pnl_state_file, {
        "date": today,
        "realised_today": float(val),
    })


def load_open_position(config: MtmConfig):
    pos = _safe_load_json(config.open_position_file, None)
    if not pos or pos.get("status") != "OPEN":
        return None
    return pos


def append_row(config: MtmConfig, row):
    config.results_file.parent.mkdir(parents=True, exist_ok=True)
    write_header = not config.results_file.exists()

    with config.results_file.open("a") as f:
        if write_header:
            f.write(
                "timestamp,trade_id,state,regime,strike,expiry,"
                "realised,unrealised,total\n"
            )

        f.write(",".join(map(str, row)) + "\n")


def compute_unrealised(config: MtmConfig, legs, ltp_map):
    unrealised = 0.0
    lot_size = APP_CONFIG.trade.lot_size

    for leg in legs:
        sid = int(leg["security_id"])
        entry_price_raw = leg.get("entry_price")

        if entry_price_raw is None:
            config.logger.error(f"ENTRY_PRICE_NONE | {leg}")
            continue

        entry_price = float(entry_price_raw)
        lots = int(leg["lots"])
        ltp = ltp_map.get(sid)

        if ltp is None:
            config.logger.error(f"{config.missing_ltp_error_code} | sid={sid} map={ltp_map}")
            return None

        qty = lot_size * lots
        if config.side == "SELL":
            unrealised += (entry_price - ltp) * qty
        else:
            unrealised += (ltp - entry_price) * qty

    return unrealised


def run(config: MtmConfig, ltp_map=None, clock=None):
    active_clock = clock or get_clock()
    now_dt = active_clock.now()
    now = now_dt.strftime("%Y-%m-%d %H:%M:%S")

    realised_today = load_realised(config, clock=active_clock)
    pos = load_open_position(config)
    last_state = load_last_state(config)

    prev_trade = last_state.get("trade_id")
    last_write_ts = last_state.get("last_write_ts")

    if last_write_ts == now:
        return

    if not pos:
        state = "FLAT"
        trade_id = ""
        regime = ""
        strike = ""
        expiry = ""
        unrealised = 0.0

        if prev_trade:
            last_unrealised = float(last_state.get("last_unrealised", 0.0))
            realised_today += last_unrealised
            save_realised(config, realised_today, clock=active_clock)
            state = "EXIT"

        append_row(config, [
            now,
            trade_id,
            state,
            regime,
            strike,
            expiry,
            f"{realised_today:.2f}",
            f"{unrealised:.2f}",
            f"{realised_today:.2f}",
        ])

        save_last_state(config, {"last_write_ts": now})
        return

    trade_id = pos["trade_id"]
    regime = pos["regime"]
    strike = pos["strike"]
    expiry = pos["expiry"]
    legs = pos.get("legs", [])

    state = "ENTRY" if trade_id != prev_trade else "OPEN"
    security_ids = [int(leg["security_id"]) for leg in legs]

    ltp_map, ltp_complete = ensure_complete_ltp_map(
        security_ids,
        ltp_map=ltp_map,
        logger=config.logger,
    )
    if config.log_shared_ltp_map:
        config.logger.info(f"LTP_MAP_SHARED | {ltp_map}")

    if not ltp_complete:
        config.logger.error(f"LTP_INCOMPLETE_SKIP_MTM | ids={security_ids} map={ltp_map}")
        return

    unrealised = compute_unrealised(config, legs, ltp_map)
    if unrealised is None:
        return

    total = realised_today + unrealised

    append_row(config, [
        now,
        trade_id,
        state,
        regime,
        strike,
        expiry,
        f"{realised_today:.2f}",
        f"{unrealised:.2f}",
        f"{total:.2f}",
    ])

    save_last_state(config, {
        "trade_id": trade_id,
        "last_unrealised": unrealised,
        "last_write_ts": now,
    })

    config.logger.info(
        f"{state} | {regime} | strike={strike} exp={expiry} | "
        f"Realised={realised_today:.2f} "
        f"Unrealised={unrealised:.2f} "
        f"Total={total:.2f}"
    )
