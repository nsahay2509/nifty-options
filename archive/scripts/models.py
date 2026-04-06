from dataclasses import asdict, dataclass, fields
from typing import Any


def _filter_kwargs(model_cls, payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {field.name for field in fields(model_cls)}
    return {key: value for key, value in payload.items() if key in allowed}


@dataclass(frozen=True)
class Candle:
    ts: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Candle":
        return cls(**_filter_kwargs(cls, payload))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PositionLeg:
    security_id: int
    entry_price: float | None = None
    lots: int = 1
    type: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PositionLeg":
        data = _filter_kwargs(cls, payload)
        if "security_id" in data:
            data["security_id"] = int(data["security_id"])
        if data.get("entry_price") is not None:
            data["entry_price"] = float(data["entry_price"])
        if "lots" in data:
            data["lots"] = int(data["lots"])
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OpenPosition:
    status: str
    trade_id: str
    regime: str
    strike: int
    expiry: str
    entry_time: str
    side: str = ""
    entry_signal: str | None = None
    entry_spot: float = 0.0
    entry_direction_score: float = 0.0
    entry_bias: float = 0.0
    legs: list[PositionLeg] | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "OpenPosition":
        data = _filter_kwargs(cls, payload)
        data["strike"] = int(data["strike"])
        if data.get("entry_spot") is not None:
            data["entry_spot"] = float(data["entry_spot"])
        if data.get("entry_direction_score") is not None:
            data["entry_direction_score"] = float(data["entry_direction_score"])
        if data.get("entry_bias") is not None:
            data["entry_bias"] = float(data["entry_bias"])
        legs = payload.get("legs", [])
        data["legs"] = [PositionLeg.from_dict(leg) for leg in legs]
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["legs"] = [leg.to_dict() for leg in (self.legs or [])]
        return data


@dataclass(frozen=True)
class SignalState:
    last_regime: str = "WAIT"
    last_signal_time: str | None = None
    candidate_regime: str = "WAIT"
    candidate_count: int = 0
    confirmed_regime: str = "WAIT"

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "SignalState":
        payload = payload or {}
        return cls(**_filter_kwargs(cls, payload))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TradeSummaryRow:
    trade_id: str
    entry_time: str
    exit_time: str
    time_in_trade_min: int
    trade_type: str
    strike: str
    expiry: str
    trade_pnl: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TradeEventRow:
    side: str
    trade_id: str
    regime: str
    entry_signal: str
    entry_time: str
    exit_time: str
    time_in_trade_min: int
    strike: str | int
    expiry: str
    entry_spot: float
    entry_direction_score: float
    entry_bias: float
    exit_reason: str
    trade_pnl: float
    entry_price: float = 0.0
    exit_price: float = 0.0
    quantity: int = 0
    exit_spot: float = 0.0
    exit_direction_score: float = 0.0
    exit_bias: float = 0.0
    peak_pnl: float = 0.0
    drawdown_from_peak: float = 0.0
    cooldown_applied_min: int = 0
    diagnostic_context: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TradeEventRow":
        data = _filter_kwargs(cls, payload)
        for int_field in ("time_in_trade_min", "cooldown_applied_min", "quantity"):
            if int_field in data and data[int_field] != "":
                data[int_field] = int(float(data[int_field]))
        for float_field in (
            "entry_spot",
            "entry_direction_score",
            "entry_bias",
            "entry_price",
            "trade_pnl",
            "exit_price",
            "exit_spot",
            "exit_direction_score",
            "exit_bias",
            "peak_pnl",
            "drawdown_from_peak",
        ):
            if float_field in data and data[float_field] != "":
                data[float_field] = float(data[float_field])
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DailySummaryRow:
    date: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    gross_pnl: float
    estimated_cost: int
    net_pnl: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
