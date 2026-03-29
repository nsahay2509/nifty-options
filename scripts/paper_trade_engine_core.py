from dataclasses import dataclass
from datetime import datetime, timedelta, time as dtime
import csv
from pathlib import Path

from scripts.app_config import APP_CONFIG, IST
from scripts.clock import get_clock
from scripts.logger import get_logger
from scripts.option_resolver import get_atm_straddle
from scripts.regime_classifier import bias as regime_bias
from scripts.regime_classifier import direction_score, load_last_candles
from scripts.state_utils import atomic_write_json, safe_load_json
from scripts.utils import fetch_ltp_map

CONFIG = APP_CONFIG.trade


@dataclass
class Position:
    trade_id: str
    regime: str
    strike: int
    expiry: str
    ce_security_id: int | None
    pe_security_id: int | None
    entry_time: datetime
    lots: int = CONFIG.lots
    side: str = ""
    entry_signal: str | None = None
    entry_spot: float = 0.0
    entry_direction_score: float = 0.0
    entry_bias: float = 0.0


class BasePaperTradeEngine:
    logger = get_logger("paper_trade_base")
    recovery_message = "Recovered OPEN position from disk"
    recovery_error_code = "OPEN_POSITION_RECOVERY_FAILED"
    stale_position_message = "STALE POSITION DETECTED -> FORCE CLOSE"
    stale_position_check_error_code = "STALE_POSITION_CHECK_FAILED"
    entry_invalid_regime_message = None

    def __init__(self, clock=None):
        self.clock = clock or get_clock()
        self.state = "FLAT"
        self.position: Position | None = None
        self.cooldown_until: datetime | None = None
        self.active_regime: str | None = None
        self.max_pnl = 0
        self.session_date = self.now().date()
        self.last_exit_regime: str | None = None
        self.last_exit_time: datetime | None = None
        self.last_exit_direction_score: float | None = None
        self.sync_from_disk()
        self.logger.info("PaperTradeEngine initialized")

    def now(self) -> datetime:
        return self.clock.now()

    def should_force_exit(self, now: datetime) -> bool:
        return now.time() >= CONFIG.force_exit_time

    def can_open_new(self, now: datetime) -> bool:
        return now.time() <= CONFIG.no_new_entry_after

    def get_open_position_file(self) -> Path:
        raise NotImplementedError

    def get_pnl_file(self) -> Path:
        raise NotImplementedError

    def get_trade_events_file(self) -> Path:
        raise NotImplementedError

    def get_side(self) -> str:
        raise NotImplementedError

    def get_reset_log_message(self, old_date, new_date) -> str:
        raise NotImplementedError

    def resolve_entry_ids(self, regime: str, atm: dict) -> tuple[int | None, int | None]:
        raise NotImplementedError

    def format_entry_message(
        self,
        regime: str,
        spot: float,
        atm: dict,
        ce_id: int | None,
        pe_id: int | None,
    ) -> str:
        raise NotImplementedError

    def compute_leg_pnl(self, entry: float, ltp: float, qty: int) -> float:
        raise NotImplementedError

    def is_tradeable_regime(self, regime: str) -> bool:
        return regime in ("SELL_PE", "SELL_CE")

    def sync_from_disk(self):
        data = safe_load_json(self.get_open_position_file(), None)
        if not data or data.get("status") != "OPEN":
            return

        try:
            entry_time = datetime.strptime(
                data["entry_time"],
                "%Y-%m-%d %H:%M:%S",
            ).replace(tzinfo=IST)
            legs = data.get("legs", [])
            ce_leg = next((leg for leg in legs if leg.get("type") == "CE"), None)
            pe_leg = next((leg for leg in legs if leg.get("type") == "PE"), None)

            self.position = Position(
                trade_id=data["trade_id"],
                regime=data["regime"],
                strike=int(data["strike"]),
                expiry=data["expiry"],
                ce_security_id=int(ce_leg["security_id"]) if ce_leg else None,
                pe_security_id=int(pe_leg["security_id"]) if pe_leg else None,
                entry_time=entry_time,
                lots=int((ce_leg or pe_leg or {}).get("lots", CONFIG.lots)),
                side=data.get("side", self.get_side()),
                entry_signal=data.get("entry_signal"),
                entry_spot=float(data.get("entry_spot", 0.0)),
                entry_direction_score=float(data.get("entry_direction_score", 0.0)),
                entry_bias=float(data.get("entry_bias", 0.0)),
            )
            self.state = "IN_POSITION"
            self.active_regime = data.get("regime")
            self.max_pnl = self.get_current_total_pnl()
            self.logger.warning(self.recovery_message)
        except Exception:
            self.logger.exception(self.recovery_error_code)

    def reset_for_new_day(self, now: datetime):
        if now.date() == self.session_date:
            return

        self.logger.info(self.get_reset_log_message(self.session_date, now.date()))
        self.state = "FLAT"
        self.position = None
        self.cooldown_until = None
        self.active_regime = None
        self.max_pnl = 0
        self.session_date = now.date()
        self.sync_from_disk()

    def write_open_position(self, pos: Position, entry_prices: dict):
        legs = []

        if pos.ce_security_id:
            ce_price = entry_prices.get(pos.ce_security_id)
            if ce_price is None:
                self.logger.error(f"ENTRY_PRICE_MISSING | CE | {pos.ce_security_id}")
                ce_price = 0.0
            legs.append({
                "security_id": pos.ce_security_id,
                "entry_price": ce_price,
                "lots": pos.lots,
                "type": "CE",
            })

        if pos.pe_security_id:
            pe_price = entry_prices.get(pos.pe_security_id)
            if pe_price is None:
                self.logger.error(f"ENTRY_PRICE_MISSING | PE | {pos.pe_security_id}")
                pe_price = 0.0
            legs.append({
                "security_id": pos.pe_security_id,
                "entry_price": pe_price,
                "lots": pos.lots,
                "type": "PE",
            })

        payload = {
            "status": "OPEN",
            "trade_id": pos.trade_id,
            "regime": pos.regime,
            "strike": pos.strike,
            "expiry": pos.expiry,
            "entry_time": pos.entry_time.strftime("%Y-%m-%d %H:%M:%S"),
            "side": pos.side,
            "entry_signal": pos.entry_signal,
            "entry_spot": pos.entry_spot,
            "entry_direction_score": pos.entry_direction_score,
            "entry_bias": pos.entry_bias,
            "legs": legs,
        }

        atomic_write_json(self.get_open_position_file(), payload, indent=2)

    def close_open_position(self):
        open_position_file = self.get_open_position_file()
        if not open_position_file.exists():
            return

        data = safe_load_json(open_position_file, None)
        if not data:
            return

        data["status"] = "CLOSED"
        atomic_write_json(open_position_file, data, indent=2)

    def clear_runtime_position(self):
        self.state = "FLAT"
        self.position = None
        self.active_regime = None
        self.max_pnl = 0

    def get_minutes_in_trade(self, now: datetime) -> float:
        if not self.position:
            return 0.0
        return (now - self.position.entry_time).total_seconds() / 60

    def can_take_same_side_reentry(self, now: datetime, regime: str, d: float) -> bool:
        if regime != self.last_exit_regime or self.last_exit_time is None:
            return True

        blocked_until = self.last_exit_time + timedelta(minutes=CONFIG.reentry_block_minutes)
        if now >= blocked_until:
            return True

        last_d = self.last_exit_direction_score if self.last_exit_direction_score is not None else 0.0
        if d >= last_d + CONFIG.reentry_min_d_improvement:
            return True

        self.logger.info(
            f"REENTRY_BLOCKED | regime={regime} d={d:.3f} last_d={last_d:.3f} until={blocked_until.strftime('%H:%M:%S')}"
        )
        return False

    def append_trade_event(self, event: dict):
        path = self.get_trade_events_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not path.exists()

        with path.open("a", newline="") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow([
                    "side",
                    "trade_id",
                    "regime",
                    "entry_signal",
                    "entry_time",
                    "exit_time",
                    "time_in_trade_min",
                    "strike",
                    "expiry",
                    "entry_spot",
                    "entry_direction_score",
                    "entry_bias",
                    "exit_reason",
                    "trade_pnl",
                ])

            writer.writerow([
                event["side"],
                event["trade_id"],
                event["regime"],
                event["entry_signal"],
                event["entry_time"],
                event["exit_time"],
                event["time_in_trade_min"],
                event["strike"],
                event["expiry"],
                event["entry_spot"],
                event["entry_direction_score"],
                event["entry_bias"],
                event["exit_reason"],
                event["trade_pnl"],
            ])

    def check_for_stale_position(self, now: datetime):
        try:
            open_position_file = self.get_open_position_file()
            if not open_position_file.exists():
                return

            data = safe_load_json(open_position_file, {})
            if data.get("status") != "OPEN":
                return

            entry_time = data.get("entry_time", "")
            entry_date = entry_time[:10]
            today = now.strftime("%Y-%m-%d")

            if entry_date and entry_date != today:
                self.logger.warning(self.stale_position_message)
                self.close_open_position()
                self.clear_runtime_position()
        except Exception:
            self.logger.exception(self.stale_position_check_error_code)

    def tick(self, signal=None, regime=None, history=None, ltp_map=None):
        now = self.now()
        self.reset_for_new_day(now)
        self.check_for_stale_position(now)

        if now.time() < CONFIG.start_scan:
            return

        if self.should_force_exit(now):
            if self.state == "IN_POSITION":
                self.exit_position(now, reason="EOD_FORCE_EXIT")

            self.state = "DONE"
            self.logger.info("Trading day completed (DONE state)")
            return

        if self.state == "COOLDOWN":
            if self.cooldown_until and now >= self.cooldown_until:
                self.logger.info("Cooldown finished -> FLAT")
                self.state = "FLAT"
            else:
                return

        if history is None:
            history = load_last_candles(CONFIG.window, clock=self.clock)

        if len(history) < CONFIG.window:
            self.logger.debug("Not enough candles yet")
            return

        self.logger.info(f"SIGNAL_CHECK | signal={signal} regime={regime}")

        current_d = direction_score(history)

        if self.state == "FLAT":
            if (
                signal
                and signal == regime
                and self.is_tradeable_regime(signal)
                and self.can_open_new(now)
                and self.can_take_same_side_reentry(now, signal, current_d)
            ):
                self.enter_position(now, signal, history, ltp_map, signal=signal)
            return

        if self.state != "IN_POSITION":
            return

        current_total = self.compute_live_pnl(ltp_map)
        self.max_pnl = max(self.max_pnl, current_total)

        if current_total <= -CONFIG.max_trade_loss:
            self.exit_position(now, reason=f"HARD_STOP {current_total:.2f}", ltp_map=ltp_map)
            self.cooldown_until = now + timedelta(minutes=CONFIG.cooldown_minutes)
            self.state = "COOLDOWN"
            self.logger.info(
                f"Hard stop hit -> cooldown until {self.cooldown_until.strftime('%H:%M:%S')}"
            )
            return

        drawdown = self.max_pnl - current_total
        minutes_in_trade = self.get_minutes_in_trade(now)
        if (
            minutes_in_trade >= CONFIG.min_hold_minutes
            and self.max_pnl >= CONFIG.profit_trail_arm
            and drawdown >= CONFIG.profit_trail_giveback
        ):
            self.exit_position(now, reason=f"TRAIL_PROFIT {drawdown:.2f}", ltp_map=ltp_map)
            self.cooldown_until = now + timedelta(minutes=CONFIG.cooldown_minutes)
            self.state = "COOLDOWN"
            self.logger.info(
                f"Profit trail hit -> cooldown until {self.cooldown_until.strftime('%H:%M:%S')}"
            )
            return

        if minutes_in_trade < CONFIG.min_hold_minutes:
            return

        if self.active_regime in ("SELL_PE", "SELL_CE") and current_d < APP_CONFIG.regime.trend_d_min:
            self.exit_position(now, reason=f"TREND_WEAK d={current_d:.2f}", ltp_map=ltp_map)
            self.cooldown_until = now + timedelta(minutes=CONFIG.cooldown_minutes)
            self.state = "COOLDOWN"
            self.logger.info(
                f"Trend weakened -> cooldown until {self.cooldown_until.strftime('%H:%M:%S')}"
            )
            return

        if regime == "WAIT" or regime == self.active_regime:
            return

        if self.is_tradeable_regime(regime):
            self.exit_position(
                now,
                reason=f"REGIME_CHANGE {self.active_regime}->{regime}",
                ltp_map=ltp_map,
            )
            self.cooldown_until = now + timedelta(minutes=CONFIG.cooldown_minutes)
            self.state = "COOLDOWN"
            self.logger.info(
                f"Entering cooldown until {self.cooldown_until.strftime('%H:%M:%S')}"
            )

    def enter_position(self, now: datetime, regime: str, history, ltp_map=None, signal=None):
        if not self.is_tradeable_regime(regime):
            if self.entry_invalid_regime_message:
                self.logger.warning(self.entry_invalid_regime_message.format(regime=regime))
            return

        spot = history[-1]["close"]
        d = direction_score(history)
        b = regime_bias(history)
        atm = get_atm_straddle(spot, clock=self.clock)
        self.max_pnl = 0
        ce_id, pe_id = self.resolve_entry_ids(regime, atm)

        trade_id = self.now().strftime("%Y%m%d_%H%M%S")
        security_ids = [sid for sid in (ce_id, pe_id) if sid]
        if ltp_map is None:
            ltp_map = fetch_ltp_map(security_ids)

        self.logger.info(f"LTP_MAP_ENTRY | ids={security_ids} map={ltp_map}")

        if not security_ids or any(ltp_map.get(sid) is None for sid in security_ids):
            self.logger.error(f"ENTRY_BLOCKED_LTP_INVALID | {ltp_map}")
            return

        self.position = Position(
            trade_id=trade_id,
            regime=regime,
            strike=atm["strike"],
            expiry=atm["expiry"],
            ce_security_id=ce_id,
            pe_security_id=pe_id,
            entry_time=now,
            lots=CONFIG.lots,
            side=self.get_side(),
            entry_signal=signal,
            entry_spot=float(spot),
            entry_direction_score=float(d),
            entry_bias=float(b),
        )

        self.state = "IN_POSITION"
        self.active_regime = regime
        self.logger.info(self.format_entry_message(regime, spot, atm, ce_id, pe_id))
        self.write_open_position(self.position, ltp_map)

    def exit_position(self, now: datetime, reason: str, ltp_map=None):
        if not self.position:
            return

        p = self.position
        live_pnl = self.compute_live_pnl(ltp_map)
        self.logger.info(
            f"EXIT | {p.regime} | strike={p.strike} "
            f"exp={p.expiry} lots={p.lots} reason={reason}"
        )

        self.append_trade_event({
            "side": p.side or self.get_side(),
            "trade_id": p.trade_id,
            "regime": p.regime,
            "entry_signal": p.entry_signal or "",
            "entry_time": p.entry_time.strftime("%Y-%m-%d %H:%M:%S"),
            "exit_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "time_in_trade_min": max(1, int(round(self.get_minutes_in_trade(now)))),
            "strike": p.strike,
            "expiry": p.expiry,
            "entry_spot": round(p.entry_spot, 2),
            "entry_direction_score": round(p.entry_direction_score, 4),
            "entry_bias": round(p.entry_bias, 2),
            "exit_reason": reason,
            "trade_pnl": round(live_pnl, 2),
        })

        self.last_exit_regime = p.regime
        self.last_exit_time = now
        self.last_exit_direction_score = p.entry_direction_score
        self.close_open_position()
        self.position = None
        self.active_regime = None
        self.state = "FLAT"

    def compute_live_pnl(self, ltp_map=None):
        if not self.position:
            return 0

        security_ids = [
            sid
            for sid in (self.position.ce_security_id, self.position.pe_security_id)
            if sid
        ]
        if not security_ids:
            return 0

        ltp_map = ltp_map or {}

        pos = safe_load_json(self.get_open_position_file(), {})
        if not pos:
            self.logger.error("OPEN_POS_READ_FAIL")
            return 0

        pnl = 0.0
        lot_size = CONFIG.lot_size

        for leg in pos.get("legs", []):
            sid = int(leg["security_id"])
            entry_raw = leg.get("entry_price")
            if entry_raw is None:
                self.logger.error(f"ENTRY_PRICE_NONE | {leg}")
                continue

            ltp = ltp_map.get(sid)
            if ltp is None:
                self.logger.error(f"LTP_MISSING_SHARED | {sid}")
                continue

            entry = float(entry_raw)
            lots = int(leg["lots"])
            qty = lot_size * lots
            pnl += self.compute_leg_pnl(entry, ltp, qty)

        return pnl

    def get_current_total_pnl(self):
        try:
            pnl_file = self.get_pnl_file()
            if not pnl_file.exists():
                return 0

            import pandas as pd

            df = pd.read_csv(pnl_file)
            if df.empty:
                return 0

            return float(df.iloc[-1]["total"])
        except Exception:
            return 0
