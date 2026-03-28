


from dataclasses import dataclass
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from pathlib import Path
import json
import uuid

from scripts.regime_classifier import load_last_candles
from scripts.option_resolver import get_atm_straddle
from scripts.utils import fetch_ltp_map
from scripts.logger import get_logger
from scripts.regime_classifier import direction_score, TREND_D_MIN
from scripts.state_utils import atomic_write_json, safe_load_json


# ==================================================
# CONFIG
# ==================================================
IST = ZoneInfo("Asia/Kolkata")
logger = get_logger("paper_trade")

START_SCAN = dtime(9, 20)
NO_NEW_ENTRY_AFTER = dtime(15, 15)
FORCE_EXIT_TIME = dtime(15, 25)

WINDOW = 25
COOLDOWN_MINUTES = 5 # changed it to 5 as we are using regime comfirmation three consecutive time. Earlier it was 10 minutes which is too long for our use case.
LOTS = 1


# ==================================================
# PATHS
# ==================================================
BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

OPEN_POS_FILE = DATA_DIR / "open_position.json"


# ==================================================
# DATA STRUCTURES
# ==================================================
@dataclass
class Position:
    trade_id: str
    regime: str
    strike: int
    expiry: str
    ce_security_id: int | None
    pe_security_id: int | None
    entry_time: datetime
    lots: int = LOTS


# ==================================================
# ENGINE
# ==================================================
class PaperTradeEngine:

    def __init__(self):
        self.state = "FLAT"     # FLAT / IN_POSITION / COOLDOWN / DONE
        self.position: Position | None = None
        self.cooldown_until: datetime | None = None
        self.active_regime: str | None = None
        self.max_pnl = 0
        self.session_date = self.now().date()
        self.sync_from_disk()

        logger.info("\n\nPaperTradeEngine initialized")

    def sync_from_disk(self):
        data = safe_load_json(OPEN_POS_FILE, None)
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
                lots=int((ce_leg or pe_leg or {}).get("lots", LOTS)),
            )
            self.state = "IN_POSITION"
            self.active_regime = data.get("regime")
            self.max_pnl = self.get_current_total_pnl()
            logger.warning("Recovered OPEN position from disk")
        except Exception:
            logger.exception("OPEN_POSITION_RECOVERY_FAILED")

    def reset_for_new_day(self, now: datetime):
        if now.date() == self.session_date:
            return

        logger.info(
            f"New trading day detected | resetting engine state from {self.session_date} to {now.date()}"
        )
        self.state = "FLAT"
        self.position = None
        self.cooldown_until = None
        self.active_regime = None
        self.max_pnl = 0
        self.session_date = now.date()
        self.sync_from_disk()

    # ------------------------------------------------
    def now(self) -> datetime:
        return datetime.now(IST)

    def should_force_exit(self, now: datetime) -> bool:
        return now.time() >= FORCE_EXIT_TIME

    def can_open_new(self, now: datetime) -> bool:
        return now.time() <= NO_NEW_ENTRY_AFTER

    # ==================================================
    # POSITION PERSISTENCE
    # ==================================================
    def write_open_position(self, pos: Position, entry_prices: dict):

        legs = []

        if pos.ce_security_id:
            legs.append({
                "security_id": pos.ce_security_id,
                "entry_price": entry_prices.get(pos.ce_security_id),
                "lots": pos.lots,
                "type": "CE",
            })

        if pos.pe_security_id:
            legs.append({
                "security_id": pos.pe_security_id,
                "entry_price": entry_prices.get(pos.pe_security_id),
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
            "legs": legs,
        }

        atomic_write_json(OPEN_POS_FILE, payload, indent=2)

    def close_open_position(self):
        if not OPEN_POS_FILE.exists():
            return

        data = safe_load_json(OPEN_POS_FILE, None)
        if not data:
            return

        data["status"] = "CLOSED"
        atomic_write_json(OPEN_POS_FILE, data, indent=2)

    # ==================================================
    # MAIN TICK
    # ==================================================
    def tick(self, signal=None, regime=None, history=None, ltp_map=None):

        now = self.now()
        self.reset_for_new_day(now)
        
        # ---- HARD STALE POSITION CLEANUP (new day safety) ----
        try:
            if OPEN_POS_FILE.exists():
                data = safe_load_json(OPEN_POS_FILE, {})

                if data.get("status") == "OPEN":
                    entry_time = data.get("entry_time", "")
                    entry_date = entry_time[:10]
                    today = now.strftime("%Y-%m-%d")

                    if entry_date and entry_date != today:
                        logger.warning("STALE POSITION DETECTED → FORCE CLOSE")
                        self.close_open_position()
                        self.state = "FLAT"
                        self.position = None
                        self.active_regime = None
        except Exception:
            logger.exception("STALE_POSITION_CHECK_FAILED")

        # ---- before scan window ----
        if now.time() < START_SCAN:
            return

        # ---- force exit ----
        if self.should_force_exit(now):
            if self.state == "IN_POSITION":
                self.exit_position(now, reason="EOD_FORCE_EXIT")

            self.state = "DONE"
            logger.info("Trading day completed (DONE state)")
            return

        # ---- cooldown ----
        if self.state == "COOLDOWN":
            if self.cooldown_until and now >= self.cooldown_until:
                logger.info("Cooldown finished → FLAT")
                self.state = "FLAT"
            else:
                return

        # ---- load candles if not provided ----
        if history is None:
            history = load_last_candles(WINDOW)

        if len(history) < WINDOW:
            logger.debug("Not enough candles yet")
            return

        # ⭐ visibility
        logger.info(f"SIGNAL_CHECK | signal={signal} regime={regime}")


        # ==================================================
        # STATE MACHINE
        # ==================================================

        if self.state == "FLAT":

            if regime in ("SELL_PE", "SELL_CE") and self.can_open_new(now):
                self.enter_position(now, regime, history, ltp_map)

            return

        # ---------------- IN POSITION ----------------
        if self.state == "IN_POSITION":

            # ---- TRAILING PNL PROTECTION ----
            current_total = self.compute_live_pnl(ltp_map)
            self.max_pnl = max(self.max_pnl, self.get_current_total_pnl())

            drawdown = self.max_pnl - current_total

            if drawdown > 800:
                self.exit_position(now, reason=f"TRAIL_DD {drawdown:.2f}")

                self.cooldown_until = now + timedelta(minutes=COOLDOWN_MINUTES)
                self.state = "COOLDOWN"

                logger.info(
                    f"Trailing DD hit → cooldown until {self.cooldown_until.strftime('%H:%M:%S')}"
                )
                return

            # ---- compute direction strength ----
            d = direction_score(history)

            # ---- EARLY EXIT: trend weakening ----
            if self.active_regime in ("SELL_PE", "SELL_CE") and d < TREND_D_MIN:
                self.exit_position(
                    now,
                    reason=f"TREND_WEAK d={d:.2f}",
                )

                self.cooldown_until = now + timedelta(minutes=COOLDOWN_MINUTES)
                self.state = "COOLDOWN"

                logger.info(
                    f"Trend weakened → cooldown until {self.cooldown_until.strftime('%H:%M:%S')}"
                )
                return


            # ---- existing behaviour ----
            if regime == "WAIT" or regime == self.active_regime:
                return

            if regime in ("SELL_PE", "SELL_CE"):

                self.exit_position(
                    now,
                    reason=f"REGIME_CHANGE {self.active_regime}->{regime}",
                )

                self.cooldown_until = now + timedelta(minutes=COOLDOWN_MINUTES)
                self.state = "COOLDOWN"

                logger.info(
                    f"Entering cooldown until {self.cooldown_until.strftime('%H:%M:%S')}"
                )
    # ==================================================
    # ENTRY
    # ==================================================
    def enter_position(self, now: datetime, regime: str, history, ltp_map=None):

        spot = history[-1]["close"]
        atm = get_atm_straddle(spot)
        self.max_pnl = 0
        ce_id = None
        pe_id = None

        if regime == "SELL_PE":
            pe_id = atm["pe_security_id"]

        elif regime == "SELL_CE":
            ce_id = atm["ce_security_id"]

        trade_id = datetime.now(IST).strftime("%Y%m%d_%H%M%S")

        # ---- fetch entry LTPs BEFORE committing position ----
        security_ids = [x for x in (ce_id, pe_id) if x]
        if ltp_map is None:
            ltp_map = fetch_ltp_map(security_ids)
        logger.info(f"LTP_MAP_ENTRY | ids={security_ids} map={ltp_map}")

        # ---- strict validation: all legs must have LTP ----
        if any(ltp_map.get(sid) is None for sid in security_ids):
            logger.error(f"ENTRY_BLOCKED_LTP_INCOMPLETE | {ltp_map}")
            return

        # ---- now safe to create position ----
        self.position = Position(
            trade_id=trade_id,
            regime=regime,
            strike=atm["strike"],
            expiry=atm["expiry"],
            ce_security_id=ce_id,
            pe_security_id=pe_id,
            entry_time=now,
            lots=LOTS,
        )

        self.state = "IN_POSITION"
        self.active_regime = regime

        logger.info(
            f"ENTRY | {regime} | spot={spot:.2f} "
            f"strike={atm['strike']} exp={atm['expiry']} "
            f"ce_id={ce_id} pe_id={pe_id} lots={LOTS}"
        )

        # ---- write with full, valid prices ----
        self.write_open_position(self.position, ltp_map)

    # ==================================================
    # EXIT
    # ==================================================
    def exit_position(self, now: datetime, reason: str):

        if not self.position:
            return

        p = self.position

        logger.info(
            f"EXIT | {p.regime} | strike={p.strike} "
            f"exp={p.expiry} lots={p.lots} reason={reason}"
        )

        self.close_open_position()

        self.position = None
        self.active_regime = None
        self.state = "FLAT"


    def compute_live_pnl(self, ltp_map=None):
        if not self.position:
            return 0

        LOT_SIZE = 50
        unrealised = 0.0

        # ---- collect security ids ----
        security_ids = []
        if self.position.ce_security_id:
            security_ids.append(self.position.ce_security_id)
        if self.position.pe_security_id:
            security_ids.append(self.position.pe_security_id)

        if not security_ids:
            return 0

        # ---- use shared LTP ----
        ltp_map = ltp_map or {}

        logger.info(f"LTP_MAP_LIVE (shared) | {ltp_map}")

        # ---- load position ----
        try:
            pos = safe_load_json(OPEN_POS_FILE, {})
        except Exception:
            logger.error("OPEN_POS_READ_FAIL")
            return 0

        # ---- compute pnl ----
        for leg in pos.get("legs", []):
            sid = int(leg["security_id"])

            entry_raw = leg.get("entry_price")
            if entry_raw is None:
                logger.error(f"ENTRY_PRICE_NONE | {leg}")
                continue

            entry = float(entry_raw)
            lots = int(leg["lots"])
            qty = LOT_SIZE * lots

            ltp = ltp_map.get(sid)
            if ltp is None:
                logger.error(f"LTP_MISSING_SHARED | {sid}")
                continue

            unrealised += (entry - ltp) * qty  # short logic

        return unrealised

    def get_current_total_pnl(self):
        try:
            pnl_file = BASE_DIR / "data" / "results" / "system_pnl.csv"

            if not pnl_file.exists():
                return 0

            import pandas as pd
            df = pd.read_csv(pnl_file)

            if df.empty:
                return 0

            return float(df.iloc[-1]["total"])

        except Exception:
            return 0

            
# ==================================================
# SINGLETON ENGINE
# ==================================================
_engine = PaperTradeEngine()


def run(signal=None, regime=None, history=None, ltp_map=None):
    _engine.tick(signal=signal, regime=regime, history=history, ltp_map=ltp_map)
