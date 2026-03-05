


from dataclasses import dataclass
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from pathlib import Path
import json
import uuid

from scripts.regime_classifier import load_last_candles
from scripts.signal_engine import generate_signal
from scripts.option_resolver import get_atm_straddle
from scripts.utils import fetch_ltp_map
from scripts.logger import get_logger


# ==================================================
# CONFIG
# ==================================================
IST = ZoneInfo("Asia/Kolkata")
logger = get_logger("paper_trade")

START_SCAN = dtime(9, 20)
NO_NEW_ENTRY_AFTER = dtime(15, 15)
FORCE_EXIT_TIME = dtime(15, 25)

WINDOW = 15
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

        logger.info("PaperTradeEngine initialized")

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

        with OPEN_POS_FILE.open("w") as f:
            json.dump(payload, f, indent=2)

    def close_open_position(self):
        if not OPEN_POS_FILE.exists():
            return

        try:
            with OPEN_POS_FILE.open() as f:
                data = json.load(f)

            data["status"] = "CLOSED"

            with OPEN_POS_FILE.open("w") as f:
                json.dump(data, f, indent=2)

        except Exception:
            pass

    # ==================================================
    # MAIN TICK
    # ==================================================
    def tick(self):

        now = self.now()

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

        # ---- load candles ----
        history = load_last_candles(WINDOW)

        if len(history) < WINDOW:
            logger.debug("Not enough candles yet")
            return

        signal, regime = generate_signal(history)

        # ⭐ visibility
        logger.info(f"SIGNAL_CHECK | signal={signal} regime={regime}")

        # ==================================================
        # STATE MACHINE
        # ==================================================

        if self.state == "FLAT":

            if signal in ("SELL_STRADDLE", "SELL_PE", "SELL_CE") and self.can_open_new(now):
                self.enter_position(now, signal, history)

            return

        # ---------------- IN POSITION ----------------
        if self.state == "IN_POSITION":

            if regime == "WAIT" or regime == self.active_regime:
                return

            if regime in ("SELL_STRADDLE", "SELL_PE", "SELL_CE"):

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
    def enter_position(self, now: datetime, regime: str, history):

        spot = history[-1]["close"]
        atm = get_atm_straddle(spot)

        ce_id = None
        pe_id = None

        if regime == "SELL_STRADDLE":
            ce_id = atm["ce_security_id"]
            pe_id = atm["pe_security_id"]
        elif regime == "SELL_PE":
            pe_id = atm["pe_security_id"]
        elif regime == "SELL_CE":
            ce_id = atm["ce_security_id"]

        trade_id = datetime.now(IST).strftime("%Y%m%d_%H%M%S")

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

        # ---- fetch entry LTPs ----
        security_ids = [x for x in (ce_id, pe_id) if x]
        ltp_map = fetch_ltp_map(security_ids)

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


# ==================================================
# SINGLETON ENGINE
# ==================================================
_engine = PaperTradeEngine()


def run():
    """
    Called once per evaluator cycle.
    """
    _engine.tick()