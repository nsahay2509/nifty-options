
# scripts/signal_engine.py


from datetime import datetime, timedelta
from pathlib import Path
import json
from zoneinfo import ZoneInfo

from scripts.regime_classifier import classify_regime


# ---------------- CONFIG ----------------
STATE_FILE = Path(__file__).resolve().parents[1] / "data" / "signal_state.json"

MIN_GAP_MINUTES = 10      # prevent over-trading
REGIME_PERSISTENCE = 2    # candles required to confirm regime


# ---------------- STATE ----------------
def load_state():
    if not STATE_FILE.exists():
        return {
            "last_regime": "WAIT",
            "last_signal_time": None,
            "candidate_regime": "WAIT",
            "candidate_count": 0,
            "confirmed_regime": "WAIT",
        }

    try:
        state = json.loads(STATE_FILE.read_text())
    except Exception:
        state = {}

    # backward compatibility (important)
    state.setdefault("last_regime", "WAIT")
    state.setdefault("last_signal_time", None)
    state.setdefault("candidate_regime", "WAIT")
    state.setdefault("candidate_count", 0)
    state.setdefault("confirmed_regime", "WAIT")

    return state


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state))


# ---------------- CORE ENGINE ----------------
def generate_signal(history):

    state = load_state()

    raw_regime = classify_regime(history)
    confirmed_regime = state["confirmed_regime"]

    candidate = state["candidate_regime"]
    count = state["candidate_count"]

    now = datetime.now(ZoneInfo("Asia/Kolkata"))

    # ==================================================
    # REGIME PERSISTENCE LOGIC
    # ==================================================
    if raw_regime == candidate:
        count += 1
    else:
        candidate = raw_regime
        count = 1

    new_confirmed = confirmed_regime

    # confirm regime only after persistence
    if count >= REGIME_PERSISTENCE:
        new_confirmed = candidate

    # ==================================================
    # SIGNAL GENERATION
    # ==================================================
    signal = None

    if (
        new_confirmed != confirmed_regime
        and new_confirmed != "WAIT"
    ):

        last_time = state["last_signal_time"]

        if last_time:
            last_time = datetime.fromisoformat(last_time)

            if now - last_time >= timedelta(minutes=MIN_GAP_MINUTES):
                signal = new_confirmed
        else:
            signal = new_confirmed

    # ==================================================
    # DIAGNOSTIC LOGGING
    # ==================================================
    print(
        f"[SIGNAL_ENGINE] "
        f"raw={raw_regime} | "
        f"candidate={candidate}({count}) | "
        f"confirmed={new_confirmed} | "
        f"signal={signal}"
    )

    # ==================================================
    # SAVE STATE
    # ==================================================
    state.update({
        "last_regime": raw_regime,
        "candidate_regime": candidate,
        "candidate_count": count,
        "confirmed_regime": new_confirmed,
    })

    if signal:
        state["last_signal_time"] = now.isoformat()

    save_state(state)

    return signal, new_confirmed


# convenience runner
if __name__ == "__main__":
    sig, regime = generate_signal(None)
    print("REGIME:", regime)
    print("SIGNAL:", sig)