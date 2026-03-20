# scripts/regime_classifier.py

from pathlib import Path
from datetime import datetime
import json
import logging


log_path = Path(__file__).resolve().parents[1] / "data" / "logs" / "regime_debug.log"

logger = logging.getLogger("regime_debug")
ENABLE_STRADDLE = False

if not logger.handlers:
    logger.setLevel(logging.INFO)

    handler = logging.FileHandler(log_path)
    formatter = logging.Formatter("%(asctime)s %(message)s")
    handler.setFormatter(formatter)

    logger.addHandler(handler)

# ---------------- CONFIG ----------------
WINDOW = 25                 # minutes used for regime detection
MIN_TRADE_TIME = (9, 20)    # avoid unstable open

# --- thresholds (tune) ---
STRADDLE_D_MAX = 0.30       # was 0.30 (looser => more straddles)
STRADDLE_COMP_MAX = 0.95    # was 0.70 (looser => more straddles)

TREND_D_MIN = 0.32          # trend threshold (keep as-is initially)

# Optional: block straddle when the last WINDOW range is too large
# (prevents selling straddle in high-vol expansion)
USE_RANGE_GUARD = True
MAX_WINDOW_RANGE_POINTS = 180.0   # adjust for NIFTY; start conservative


# ---------------- DATA LOADER ----------------
def load_last_candles(n: int):
    base_dir = Path(__file__).resolve().parents[1]
    spot_dir = base_dir / "data" / "spot"

    today = datetime.now().strftime("%Y-%m-%d")
    file_path = spot_dir / f"{today}.jsonl"

    if not file_path.exists():
        return []

    with open(file_path, "r") as f:
        lines = f.readlines()

    return [json.loads(x) for x in lines[-n:]]


# ---------------- METRICS ----------------
def direction_score(candles):
    """
    0 → choppy
    1 → strong trend
    """
    open_first = candles[0]["open"]
    close_last = candles[-1]["close"]

    net_move = abs(close_last - open_first)
    sum_ranges = sum((c["high"] - c["low"]) for c in candles)

    if sum_ranges <= 0:
        return 0.0

    return net_move / sum_ranges


def bias(candles):
    return candles[-1]["close"] - candles[0]["open"]


def compression_score(candles):
    """
    <1 → volatility shrinking
    """
    first5 = candles[:5]
    last5 = candles[-5:]

    r1 = max(c["high"] for c in first5) - min(c["low"] for c in first5)
    r2 = max(c["high"] for c in last5) - min(c["low"] for c in last5)

    if r1 <= 0:
        return 1.0

    return r2 / r1


def window_range(candles):
    return max(c["high"] for c in candles) - min(c["low"] for c in candles)


# ---------------- REGIME ENGINE ----------------
def classify_regime(candles=None):
    if candles is None:
        candles = load_last_candles(WINDOW)

    if len(candles) < WINDOW:
        return "WAIT"

    # avoid early noise
    ts = candles[-1]["ts"]
    dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    if (dt.hour, dt.minute) < MIN_TRADE_TIME:
        return "WAIT"

    # ---- metrics ----
    d = direction_score(candles)
    b = bias(candles)
    comp = compression_score(candles)
    rng = window_range(candles)

    # ---- debug log (always print) ----
    logger.info(f"{ts} | d={d:.3f} b={b:.1f} comp={comp:.2f} range={rng:.1f}")

    # ---- straddle regime ----
    if ENABLE_STRADDLE:
        if d <= STRADDLE_D_MAX and comp <= STRADDLE_COMP_MAX:
            if not USE_RANGE_GUARD or rng <= MAX_WINDOW_RANGE_POINTS:
                return "SELL_STRADDLE"

    # ---- trend regimes ----
    if d >= TREND_D_MIN:
        if b > 20:
            return "SELL_PE"
        if b < -5:
            return "SELL_CE"

    return "WAIT"


def get_regime():
    return classify_regime()


if __name__ == "__main__":
    print(get_regime())