"""Abstract broker contract used by the rebuilt system."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .types import (
    BrokerOrderBookEntry,
    BrokerOrderStatus,
    BrokerPosition,
    CandleRequest,
    OrderRequest,
    OrderResult,
    QuoteRequest,
)


class BrokerInterface(ABC):
    """Common broker contract so the rest of the system stays broker-agnostic."""

    @abstractmethod
    def get_intraday_candles(self, request: CandleRequest) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_option_chain(self, *, underlying_security_id: str, exchange_segment: str, expiry: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_option_expiries(self, *, underlying_security_id: str, exchange_segment: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_quote(self, request: QuoteRequest) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def place_order(self, request: OrderRequest) -> OrderResult:
        raise NotImplementedError

    @abstractmethod
    def get_order_status(self, order_id: str) -> BrokerOrderStatus:
        raise NotImplementedError

    @abstractmethod
    def get_positions(self) -> list[BrokerPosition]:
        raise NotImplementedError

    @abstractmethod
    def get_order_book(self) -> list[BrokerOrderBookEntry]:
        raise NotImplementedError
