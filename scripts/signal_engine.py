


# scripts/signal_engine.py

from datetime import datetime, timedelta
from pathlib import Path
import json

from scripts.regime_classifier import classify_regime


# ---------------- CONFIG ----------------
STATE_FILE = Path(__file__).resolve().parents[1] / "data" / "signal_state.json"

MIN_GAP_MINUTES = 20   # prevent over-trading


# ---------------- STATE ----------------
def load_state():
    if not STATE_FILE.exists():
        return {
            "last_regime": "WAIT",
            "last_signal_time": None,
        }

    try:
        return json.loads(STATE_FILE.read_text())
    except:
        return {
            "last_regime": "WAIT",
            "last_signal_time": None,
        }


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state))


# ---------------- CORE ENGINE ----------------
def generate_signal(history):

    state = load_state()

    prev_regime = state["last_regime"]
    current_regime = classify_regime(history)

    now = datetime.now()

    # ---------- transition filter ----------
    signal = None

    if current_regime != "WAIT" and current_regime != prev_regime:

        # ---------- cooldown filter ----------
        last_time = state["last_signal_time"]

        if last_time:
            last_time = datetime.fromisoformat(last_time)

            if now - last_time < timedelta(minutes=MIN_GAP_MINUTES):
                signal = None
            else:
                signal = current_regime
        else:
            signal = current_regime

    # ---------- update state ----------
    state["last_regime"] = current_regime

    if signal:
        state["last_signal_time"] = now.isoformat()

    save_state(state)

    return signal, current_regime


# convenience runner
if __name__ == "__main__":
    sig, regime = generate_signal(None)
    print("REGIME:", regime)
    print("SIGNAL:", sig)