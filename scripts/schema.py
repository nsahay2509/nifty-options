"""Core domain objects for the rebuilt NIFTY system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class MarketInstrument:
    """Represents a tradable or reference market instrument."""

    name: str
    exchange_segment: str
    security_id: str
    instrument_type: str
    expiry: str = ""
    strike: float = 0.0
    option_type: str = ""
    lot_size: int = 1


@dataclass(frozen=True)
class MarketTick:
    """Represents one normalized market-data tick or quote event."""

    instrument: MarketInstrument
    timestamp: datetime
    ltp: float
    ltq: int = 0
    ltt_epoch: int = 0
    atp: float = 0.0
    volume: int = 0
    total_buy_qty: int = 0
    total_sell_qty: int = 0
    open_interest: int = 0
    day_open: float = 0.0
    day_high: float = 0.0
    day_low: float = 0.0
    prev_close: float = 0.0
    best_bid_price: float = 0.0
    best_ask_price: float = 0.0
    best_bid_quantity: int = 0
    best_ask_quantity: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Candle:
    """Represents a normalized OHLCV candle."""

    instrument: MarketInstrument
    interval_min: int
    start: datetime
    end: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int = 0
    open_interest: int = 0
    tick_count: int = 0


@dataclass(frozen=True)
class PriorDayLevels:
    """Represents previous-session reference levels."""

    session_date: str
    open: float
    high: float
    low: float
    close: float
    midpoint: float
    range_points: float


@dataclass(frozen=True)
class SessionReferences:
    """Represents reusable intraday session reference levels."""

    session_date: str
    opening_range_high: float
    opening_range_low: float
    intraday_high: float
    intraday_low: float
    session_midpoint: float
    realized_range: float
    derived_from_interval_min: int = 1


@dataclass(frozen=True)
class SessionSnapshot:
    """Represents the current session context used for state evaluation."""

    timestamp: datetime
    index_candle: Candle | None = None
    futures_candle: Candle | None = None
    prior_day_levels: PriorDayLevels | None = None
    session_references: SessionReferences | None = None
    days_to_expiry: int | None = None
    session_phase: str = ""
    raw_context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StateAssessment:
    """Represents the market state chosen by the state engine."""

    state_name: str = ""
    confidence: str = ""
    ambiguity: str = ""
    tradeable: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlaybookDecision:
    """Represents the playbook selected for the current state."""

    playbook_name: str = ""
    reason: str = ""
    no_trade: bool = False
    alternatives: tuple[str, ...] = ()


@dataclass(frozen=True)
class StructureProposal:
    """Represents the concrete trade structure proposed by the system."""

    structure_type: str = ""
    expiry: str = ""
    strikes: tuple[float, ...] = ()
    estimated_premium: float = 0.0
    notes: str = ""


@dataclass(frozen=True)
class TradeRecord:
    """Represents a fully attributed trade lifecycle record."""

    trade_id: str = ""
    state_at_entry: str = ""
    playbook: str = ""
    structure_type: str = ""
    gross_pnl: float = 0.0
    fees_and_costs: float = 0.0
    net_pnl: float = 0.0
