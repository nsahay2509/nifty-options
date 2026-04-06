"""Dhan broker adapter implementation."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from scripts.config import APP_CONFIG
from scripts.log import get_logger

from .base import BrokerInterface
from .types import (
    BrokerCredentials,
    BrokerOrderBookEntry,
    BrokerOrderStatus,
    BrokerPosition,
    CandleRequest,
    OrderRequest,
    OrderResult,
    QuoteRequest,
)


class DhanBrokerError(RuntimeError):
    """Raised when the Dhan adapter receives an error response."""


class DhanBroker(BrokerInterface):
    """Thin Dhan adapter that normalizes broker communication behind one interface."""

    BASE_URL = "https://api.dhan.co"

    def __init__(self, credentials: BrokerCredentials, *, timeout_sec: int | None = None) -> None:
        self.credentials = credentials
        self.timeout_sec = timeout_sec or APP_CONFIG.broker.request_timeout_sec
        self.logger = get_logger("brokers.dhan")

    def get_intraday_candles(self, request: CandleRequest) -> dict[str, Any]:
        payload = {
            "securityId": request.security_id,
            "exchangeSegment": request.exchange_segment,
            "instrument": request.instrument,
            "fromDate": request.from_date,
            "toDate": request.to_date,
            "interval": request.interval,
        }
        return self._post("/charts/intraday", payload)

    def get_option_chain(self, *, underlying_security_id: str, exchange_segment: str, expiry: str) -> dict[str, Any]:
        payload = {
            "UnderlyingScrip": int(underlying_security_id),
            "UnderlyingSeg": exchange_segment,
            "Expiry": expiry,
        }
        return self._post("/v2/optionchain", payload)

    def get_option_expiries(self, *, underlying_security_id: str, exchange_segment: str) -> dict[str, Any]:
        payload = {
            "UnderlyingScrip": int(underlying_security_id),
            "UnderlyingSeg": exchange_segment,
        }
        return self._post("/v2/optionchain/expirylist", payload)

    def get_quote(self, request: QuoteRequest) -> dict[str, Any]:
        payload = {
            "NSE_EQ": [],
            "NSE_FNO": [
                {
                    "securityId": int(request.security_id),
                    "exchangeSegment": request.exchange_segment,
                }
            ],
        }
        return self._post("/v2/marketfeed/ltp", payload)

    def place_order(self, request: OrderRequest) -> OrderResult:
        payload = {
            "securityId": request.security_id,
            "exchangeSegment": request.exchange_segment,
            "transactionType": request.transaction_type.value,
            "quantity": request.quantity,
            "orderType": request.order_type.value,
            "productType": request.product_type.value,
            "price": request.price,
            "triggerPrice": request.trigger_price,
            "validity": request.validity,
            "disclosedQuantity": request.disclosed_quantity,
            "afterMarketOrder": request.after_market_order,
        }
        if request.tag:
            payload["correlationId"] = request.tag
        payload.update(request.raw_fields)
        response = self._post("/v2/orders", payload)
        return OrderResult(
            order_id=str(response.get("orderId", "")),
            status=str(response.get("orderStatus", "submitted")),
            raw=response,
        )

    def get_order_status(self, order_id: str) -> BrokerOrderStatus:
        response = self._get(f"/v2/orders/{order_id}")
        return BrokerOrderStatus(
            order_id=order_id,
            status=str(response.get("orderStatus", "")),
            filled_quantity=int(response.get("filledQty", 0) or 0),
            remaining_quantity=int(response.get("remainingQuantity", 0) or 0),
            average_price=float(response.get("averageTradedPrice", 0.0) or 0.0),
            raw=response,
        )

    def get_positions(self) -> list[BrokerPosition]:
        response = self._get("/v2/positions")
        positions = response if isinstance(response, list) else response.get("data", [])
        return [
            BrokerPosition(
                security_id=str(item.get("securityId", "")),
                exchange_segment=str(item.get("exchangeSegment", "")),
                product_type=str(item.get("productType", "")),
                quantity=int(item.get("netQty", 0) or 0),
                average_price=float(item.get("buyAvg", item.get("averagePrice", 0.0)) or 0.0),
                raw=item,
            )
            for item in positions
        ]

    def get_order_book(self) -> list[BrokerOrderBookEntry]:
        response = self._get("/v2/orders")
        orders = response if isinstance(response, list) else response.get("data", [])
        return [
            BrokerOrderBookEntry(
                order_id=str(item.get("orderId", "")),
                status=str(item.get("orderStatus", "")),
                security_id=str(item.get("securityId", "")),
                transaction_type=str(item.get("transactionType", "")),
                quantity=int(item.get("quantity", 0) or 0),
                raw=item,
            )
            for item in orders
        ]

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "access-token": self.credentials.access_token,
            "client-id": self.credentials.client_id,
        }

    def _get(self, path: str) -> dict[str, Any]:
        return self._request("GET", path)

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, payload)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            url=f"{self.BASE_URL}{path}",
            data=body,
            headers=self._headers(),
            method=method,
        )

        self.logger.info("BROKER_REQUEST | broker=dhan method=%s path=%s", method, path)
        try:
            with urlopen(request, timeout=self.timeout_sec) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise DhanBrokerError(f"Dhan HTTP error {exc.code} for {path}: {detail}") from exc
        except URLError as exc:
            raise DhanBrokerError(f"Dhan network error for {path}: {exc}") from exc
