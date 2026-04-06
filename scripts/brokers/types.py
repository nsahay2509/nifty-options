"""Broker-facing request and response models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS = "STOP_LOSS"
    STOP_LOSS_MARKET = "STOP_LOSS_MARKET"


class ProductType(StrEnum):
    INTRADAY = "INTRADAY"
    DELIVERY = "DELIVERY"
    MTF = "MTF"


@dataclass(frozen=True)
class BrokerCredentials:
    client_id: str
    access_token: str


@dataclass(frozen=True)
class CandleRequest:
    security_id: str
    exchange_segment: str
    instrument: str
    from_date: str
    to_date: str
    interval: str = "1"


@dataclass(frozen=True)
class QuoteRequest:
    security_id: str
    exchange_segment: str


@dataclass(frozen=True)
class OrderRequest:
    security_id: str
    exchange_segment: str
    transaction_type: OrderSide
    quantity: int
    order_type: OrderType
    product_type: ProductType
    price: float = 0.0
    trigger_price: float = 0.0
    validity: str = "DAY"
    disclosed_quantity: int = 0
    after_market_order: bool = False
    tag: str = ""
    raw_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderResult:
    order_id: str
    status: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class BrokerOrderStatus:
    order_id: str
    status: str
    filled_quantity: int
    remaining_quantity: int
    average_price: float
    raw: dict[str, Any]


@dataclass(frozen=True)
class BrokerPosition:
    security_id: str
    exchange_segment: str
    product_type: str
    quantity: int
    average_price: float
    raw: dict[str, Any]


@dataclass(frozen=True)
class BrokerOrderBookEntry:
    order_id: str
    status: str
    security_id: str
    transaction_type: str
    quantity: int
    raw: dict[str, Any]
