"""Instrument-resolution helpers for the rebuilt system."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from scripts.config import APP_CONFIG, FuturesRolloverRule
from scripts.log import get_logger
from scripts.schema import MarketInstrument


logger = get_logger("instrument_resolver")


@dataclass(frozen=True)
class ResolvedBaseInstruments:
    """Resolved base instruments used by the market-data layer."""

    index: MarketInstrument
    futures: MarketInstrument


def _load_instrument_rows(path: Path) -> list[dict[str, str]]:
    with path.open() as f:
        return list(csv.DictReader(f))


def resolve_nifty_index(path: str | Path | None = None) -> MarketInstrument:
    """Resolve the Nifty 50 index instrument."""
    instrument_master = Path(path or APP_CONFIG.broker.instrument_master_file)
    rows = _load_instrument_rows(instrument_master)

    for row in rows:
        if (
            (row.get("EXCH_ID") or "").strip() == "NSE"
            and (row.get("SEGMENT") or "").strip() == "I"
            and (row.get("INSTRUMENT_TYPE") or "").strip() == "INDEX"
            and (row.get("UNDERLYING_SYMBOL") or "").strip() == "NIFTY"
        ):
            return MarketInstrument(
                name="NIFTY_50_INDEX",
                exchange_segment="IDX_I",
                security_id=(row.get("SECURITY_ID") or "").strip(),
                instrument_type="INDEX",
            )

    raise ValueError("Could not resolve Nifty 50 index instrument from instrument master")


def resolve_nifty_current_month_future(
    *,
    as_of: date | None = None,
    path: str | Path | None = None,
) -> MarketInstrument:
    """Resolve the nearest unexpired Nifty future."""
    instrument_master = Path(path or APP_CONFIG.broker.instrument_master_file)
    rows = _load_instrument_rows(instrument_master)
    as_of_date = as_of or date.today()

    candidates: list[tuple[date, dict[str, str]]] = []
    for row in rows:
        if (
            (row.get("EXCH_ID") or "").strip() == "NSE"
            and (row.get("SEGMENT") or "").strip() == "D"
            and (row.get("INSTRUMENT_TYPE") or "").strip() == "FUT"
            and (row.get("UNDERLYING_SYMBOL") or "").strip() == "NIFTY"
        ):
            expiry_raw = (row.get("SM_EXPIRY_DATE") or "").strip()
            if not expiry_raw:
                continue
            expiry = datetime.strptime(expiry_raw, "%Y-%m-%d").date()
            if expiry >= as_of_date:
                candidates.append((expiry, row))

    if not candidates:
        raise ValueError("Could not resolve current-month Nifty future from instrument master")

    selected = _select_active_future(candidates, as_of_date)
    expiry, row = selected
    return MarketInstrument(
        name="NIFTY_CURRENT_MONTH_FUT",
        exchange_segment="NSE_FNO",
        security_id=(row.get("SECURITY_ID") or "").strip(),
        instrument_type="FUTURES",
        expiry=expiry.isoformat(),
    )


def _select_active_future(
    candidates: list[tuple[date, dict[str, str]]],
    as_of_date: date,
) -> tuple[date, dict[str, str]]:
    """Select the active future using the configured rollover policy."""
    ordered = sorted(candidates, key=lambda item: item[0])
    rule = APP_CONFIG.market_data.futures_rollover_rule
    buffer_days = APP_CONFIG.market_data.futures_rollover_buffer_days

    if rule == FuturesRolloverRule.NEAR_MONTH_UNTIL_EXPIRY:
        for expiry, row in ordered:
            if expiry >= as_of_date:
                return expiry, row
        return ordered[-1]

    if rule == FuturesRolloverRule.NEXT_TRADING_DAY_AFTER_EXPIRY:
        for expiry, row in ordered:
            if expiry >= as_of_date:
                if buffer_days > 0 and (expiry - as_of_date).days <= buffer_days:
                    idx = ordered.index((expiry, row))
                    if idx + 1 < len(ordered):
                        return ordered[idx + 1]
                return expiry, row
        return ordered[-1]

    return ordered[0]


def resolve_base_instruments(
    *,
    as_of: date | None = None,
    path: str | Path | None = None,
) -> ResolvedBaseInstruments:
    """Resolve the default base index and current-month futures instruments."""
    index = resolve_nifty_index(path)
    futures = resolve_nifty_current_month_future(as_of=as_of, path=path)
    logger.info(
        "BASE_INSTRUMENTS | index_sid=%s futures_sid=%s futures_expiry=%s",
        index.security_id,
        futures.security_id,
        futures.expiry,
    )
    return ResolvedBaseInstruments(index=index, futures=futures)
