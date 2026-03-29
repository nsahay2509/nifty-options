# scripts/regime_classifier.py

from pathlib import Path
from datetime import datetime
import json
import logging

from scripts.app_config import APP_CONFIG
from scripts.clock import get_clock

log_path = Path(__file__).resolve().parents[1] / "data" / "logs" / "regime_debug.log"

logger = logging.getLogger("regime_debug")
CONFIG = APP_CONFIG.regime

if not logger.handlers:
    logger.setLevel(logging.INFO)

    handler = logging.FileHandler(log_path)
    formatter = logging.Formatter("%(asctime)s %(message)s")
    handler.setFormatter(formatter)

    logger.addHandler(handler)

# ---------------- DATA LOADER ----------------
def load_last_candles(n: int, clock=None):
    base_dir = Path(__file__).resolve().parents[1]
    spot_dir = base_dir / "data" / "spot"

    active_clock = clock or get_clock()
    today = active_clock.today().strftime("%Y-%m-%d")
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
def classify_regime(candles=None, clock=None):
    if candles is None:
        candles = load_last_candles(CONFIG.window, clock=clock)

    if len(candles) < CONFIG.window:
        return "WAIT"

    # avoid early noise
    ts = candles[-1]["ts"]
    dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    if (dt.hour, dt.minute) < CONFIG.min_trade_time:
        return "WAIT"

    # ---- metrics ----
    d = direction_score(candles)
    b = bias(candles)
    comp = compression_score(candles)
    rng = window_range(candles)

    # ---- debug log (always print) ----
    logger.info(f"{ts} | d={d:.3f} b={b:.1f} comp={comp:.2f} range={rng:.1f}")

    # ---- straddle regime ----
    if CONFIG.enable_straddle:
        if d <= CONFIG.straddle_d_max and comp <= CONFIG.straddle_comp_max:
            if not CONFIG.use_range_guard or rng <= CONFIG.max_window_range_points:
                return "SELL_STRADDLE"

    # ---- trend regimes ----
    if d >= CONFIG.trend_d_min:
        if b > 20:
            return "SELL_PE"
        if b < -5:
            return "SELL_CE"

    return "WAIT"


def get_regime():
    return classify_regime()


if __name__ == "__main__":
    print(get_regime())
