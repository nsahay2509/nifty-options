"""Resolve NIFTY option instruments for live paper monitoring and MTM."""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

from scripts.config import APP_CONFIG
from scripts.log import get_logger
from scripts.schema import MarketInstrument


logger = get_logger("option_resolver")
_OPTION_CACHE: dict[Path, list[dict[str, str]]] = {}


def _load_nifty_option_rows(path: str | Path | None = None) -> list[dict[str, str]]:
    instrument_master = Path(path or APP_CONFIG.broker.instrument_master_file)
    cached = _OPTION_CACHE.get(instrument_master)
    if cached is not None:
        return cached

    with instrument_master.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))

    filtered = [
        row
        for row in rows
        if (row.get("EXCH_ID") or "").strip() == "NSE"
        and (row.get("SEGMENT") or "").strip() == "D"
        and (row.get("INSTRUMENT") or "").strip() == "OPTIDX"
        and (row.get("UNDERLYING_SYMBOL") or "").strip() == "NIFTY"
    ]
    _OPTION_CACHE[instrument_master] = filtered
    return filtered


def _parse_expiry(raw: str) -> date:
    return datetime.strptime(raw.strip(), "%Y-%m-%d").date()


def available_nifty_expiries(*, as_of: date | None = None, path: str | Path | None = None) -> list[date]:
    as_of_date = as_of or date.today()
    expiries = {
        _parse_expiry(row["SM_EXPIRY_DATE"])
        for row in _load_nifty_option_rows(path)
        if row.get("SM_EXPIRY_DATE")
    }
    return sorted(expiry for expiry in expiries if expiry >= as_of_date)


def _select_expiry(expiries: list[date], expiry_hint: str, as_of_date: date) -> date:
    if not expiries:
        raise ValueError("No unexpired NIFTY option expiries found")

    if expiry_hint == "same_day":
        for expiry in expiries:
            if expiry == as_of_date:
                return expiry
        return expiries[0]

    if expiry_hint == "next_week" and len(expiries) > 1:
        return expiries[1]

    return expiries[0]


def resolve_nifty_option(
    *,
    strike: float,
    option_type: str,
    expiry_hint: str = "same_week",
    as_of: date | None = None,
    path: str | Path | None = None,
) -> MarketInstrument:
    """Resolve one NIFTY option contract from the instrument master."""
    as_of_date = as_of or date.today()
    expiry = _select_expiry(available_nifty_expiries(as_of=as_of_date, path=path), expiry_hint, as_of_date)
    target_option_type = option_type.upper().strip()
    target_strike = float(strike)

    for row in _load_nifty_option_rows(path):
        if _parse_expiry(row.get("SM_EXPIRY_DATE") or "") != expiry:
            continue
        if (row.get("OPTION_TYPE") or "").strip().upper() != target_option_type:
            continue
        if float(row.get("STRIKE_PRICE") or 0.0) != target_strike:
            continue

        return MarketInstrument(
            name=(row.get("DISPLAY_NAME") or row.get("SYMBOL_NAME") or f"NIFTY_{target_strike}_{target_option_type}").strip(),
            exchange_segment="NSE_FNO",
            security_id=(row.get("SECURITY_ID") or "").strip(),
            instrument_type="OPTION",
            expiry=expiry.isoformat(),
            strike=target_strike,
            option_type=target_option_type,
            lot_size=int(float(row.get("LOT_SIZE") or 1) or 1),
        )

    raise ValueError(
        f"Could not resolve NIFTY option strike={target_strike} option_type={target_option_type} expiry_hint={expiry_hint}"
    )


def resolve_nifty_option_basket(
    *,
    center_price: float,
    expiry_hint: str = "same_week",
    as_of: date | None = None,
    strike_step: int = 50,
    breadth_steps: int = 6,
    path: str | Path | None = None,
) -> list[MarketInstrument]:
    """Resolve a nearby CE/PE basket around the current ATM for live MTM marking."""
    if center_price <= 0:
        return []

    atm = round(center_price / strike_step) * strike_step
    instruments: list[MarketInstrument] = []
    seen: set[str] = set()

    for offset in range(-breadth_steps, breadth_steps + 1):
        strike = float(atm + (offset * strike_step))
        for option_type in ("CE", "PE"):
            try:
                instrument = resolve_nifty_option(
                    strike=strike,
                    option_type=option_type,
                    expiry_hint=expiry_hint,
                    as_of=as_of,
                    path=path,
                )
            except ValueError:
                continue
            if instrument.security_id in seen:
                continue
            seen.add(instrument.security_id)
            instruments.append(instrument)

    logger.info(
        "OPTION_BASKET | center_price=%s expiry_hint=%s count=%s",
        center_price,
        expiry_hint,
        len(instruments),
    )
    return instruments
