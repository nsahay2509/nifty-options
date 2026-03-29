


# scripts/option_resolver.py



from pathlib import Path
import pandas as pd

from scripts.clock import get_clock

BASE_DIR = Path(__file__).resolve().parents[1]
INSTRUMENT_FILE = BASE_DIR / "data" / "dhan_instruments.csv"

_df = None


# -------------------------------------------------
# LOAD + CACHE INSTRUMENTS
# -------------------------------------------------
def load_instruments():
    global _df

    if _df is not None:
        return _df

    df = pd.read_csv(INSTRUMENT_FILE, low_memory=False)

    # Keep only NIFTY index options
    df = df[
        (df["INSTRUMENT"] == "OPTIDX") &
        (df["UNDERLYING_SYMBOL"] == "NIFTY")
    ].copy()

    # normalize types
    df["STRIKE_PRICE"] = df["STRIKE_PRICE"].astype(float)
    df["SM_EXPIRY_DATE"] = pd.to_datetime(df["SM_EXPIRY_DATE"])

    _df = df
    return _df


# -------------------------------------------------
# GET NEAREST EXPIRY
# -------------------------------------------------
def get_nearest_expiry(df, clock=None):
    active_clock = clock or get_clock()
    today = pd.Timestamp(active_clock.today())

    expiries = sorted(
        e for e in df["SM_EXPIRY_DATE"].unique()
        if e >= today
    )

    if not expiries:
        raise RuntimeError("No valid expiry found")

    return expiries[0]


# -------------------------------------------------
# ATM STRADDLE RESOLVER
# -------------------------------------------------
def get_atm_straddle(spot: float, clock=None):

    df = load_instruments()

    # NIFTY strike spacing
    strike = round(spot / 50) * 50

    expiry = get_nearest_expiry(df, clock=clock)

    df_exp = df[
        (df["SM_EXPIRY_DATE"] == expiry) &
        (df["STRIKE_PRICE"] == strike)
    ]

    if df_exp.empty:
        raise RuntimeError(f"No options found for strike {strike}")

    ce = df_exp[df_exp["OPTION_TYPE"] == "CE"].iloc[0]
    pe = df_exp[df_exp["OPTION_TYPE"] == "PE"].iloc[0]

    return {
        "strike": int(strike),
        "expiry": expiry.strftime("%Y-%m-%d"),

        "ce_security_id": int(ce["SECURITY_ID"]),
        "pe_security_id": int(pe["SECURITY_ID"]),

        "ce_symbol": ce["DISPLAY_NAME"],
        "pe_symbol": pe["DISPLAY_NAME"],
    }
