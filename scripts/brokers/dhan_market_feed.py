"""Dhan WebSocket market-feed support for normalized tick streaming."""

from __future__ import annotations

import asyncio
import json
import struct
from datetime import UTC, datetime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from scripts.config import APP_CONFIG, MarketFeedMode
from scripts.log import get_logger
from scripts.schema import MarketInstrument, MarketTick

from .types import BrokerCredentials

try:
    import websockets
except ImportError:  # pragma: no cover - optional runtime dependency
    websockets = None


SEGMENT_BY_CODE = {
    0: "",
    1: "NSE_EQ",
    2: "NSE_FNO",
    3: "NSE_CURR",
    4: "MCX_COMM",
    5: "BSE_EQ",
    8: "BSE_FNO",
    13: "IDX_I",
}

REQUEST_CODE_BY_MODE = {
    MarketFeedMode.TICKER: 15,
    MarketFeedMode.QUOTE: 17,
    MarketFeedMode.FULL: 21,
}


class DhanMarketFeed:
    """Thin websocket client that normalizes Dhan market feed into MarketTick objects."""

    def __init__(
        self,
        credentials: BrokerCredentials,
        *,
        mode: MarketFeedMode | None = None,
    ) -> None:
        self.credentials = credentials
        self.mode = mode or APP_CONFIG.market_data.base_feed_mode
        self.market_timezone = ZoneInfo(APP_CONFIG.session.market_timezone)
        self.logger = get_logger("brokers.dhan_feed")

    def _decode_timestamp(self, ltt_epoch: int) -> datetime:
        """Normalize Dhan's LTT field into the configured market timezone.

        The live feed currently emits LTT values aligned to IST wall-clock time,
        so we preserve the wall-clock fields and attach the exchange timezone.
        """
        if ltt_epoch <= 0:
            return datetime.now(self.market_timezone)
        return datetime.fromtimestamp(ltt_epoch, tz=UTC).replace(tzinfo=self.market_timezone)

    def websocket_url(self) -> str:
        query = urlencode(
            {
                "version": 2,
                "token": self.credentials.access_token,
                "clientId": self.credentials.client_id,
                "authType": 2,
            }
        )
        return f"wss://api-feed.dhan.co?{query}"

    async def stream(self, instruments: list[MarketInstrument]):
        """Yield normalized market ticks from the Dhan websocket."""
        if websockets is None:
            raise RuntimeError("websockets package is required to use DhanMarketFeed")

        instrument_map = {inst.security_id: inst for inst in instruments}
        async with websockets.connect(self.websocket_url(), ping_interval=10, ping_timeout=40) as ws:
            await ws.send(self._subscription_message(instruments))
            self.logger.info("MARKET_FEED_CONNECTED | instruments=%s mode=%s", len(instruments), self.mode.value)

            while True:
                raw = await ws.recv()
                if isinstance(raw, str):
                    self.logger.info("MARKET_FEED_TEXT | payload=%s", raw)
                    continue

                tick = self._parse_binary(raw, instrument_map)
                if tick is not None:
                    yield tick

    def _subscription_message(self, instruments: list[MarketInstrument]) -> str:
        payload = {
            "RequestCode": REQUEST_CODE_BY_MODE[self.mode],
            "InstrumentCount": len(instruments),
            "InstrumentList": [
                {
                    "ExchangeSegment": inst.exchange_segment,
                    "SecurityId": inst.security_id,
                }
                for inst in instruments
            ],
        }
        return json.dumps(payload)

    def _parse_binary(
        self,
        payload: bytes,
        instrument_map: dict[str, MarketInstrument],
    ) -> MarketTick | None:
        if len(payload) < 8:
            return None

        response_code = payload[0]
        exchange_segment_code = payload[3]
        security_id = str(struct.unpack("<I", payload[4:8])[0])
        instrument = instrument_map.get(security_id)
        if instrument is None:
            instrument = MarketInstrument(
                name=f"UNKNOWN_{security_id}",
                exchange_segment=SEGMENT_BY_CODE.get(exchange_segment_code, ""),
                security_id=security_id,
                instrument_type="UNKNOWN",
            )

        if response_code == 2 and len(payload) >= 16:
            ltp = struct.unpack("<f", payload[8:12])[0]
            ltt_epoch = struct.unpack("<I", payload[12:16])[0]
            return MarketTick(
                instrument=instrument,
                timestamp=self._decode_timestamp(ltt_epoch),
                ltp=ltp,
                ltt_epoch=ltt_epoch,
                raw={"response_code": response_code},
            )

        if response_code == 4 and len(payload) >= 50:
            ltp = struct.unpack("<f", payload[8:12])[0]
            ltq = struct.unpack("<H", payload[12:14])[0]
            ltt_epoch = struct.unpack("<I", payload[14:18])[0]
            atp = struct.unpack("<f", payload[18:22])[0]
            volume = struct.unpack("<I", payload[22:26])[0]
            total_sell_qty = struct.unpack("<I", payload[26:30])[0]
            total_buy_qty = struct.unpack("<I", payload[30:34])[0]
            day_open = struct.unpack("<f", payload[34:38])[0]
            day_high = struct.unpack("<f", payload[42:46])[0]
            day_low = struct.unpack("<f", payload[46:50])[0]
            return MarketTick(
                instrument=instrument,
                timestamp=self._decode_timestamp(ltt_epoch),
                ltp=ltp,
                ltq=ltq,
                ltt_epoch=ltt_epoch,
                atp=atp,
                volume=volume,
                total_buy_qty=total_buy_qty,
                total_sell_qty=total_sell_qty,
                day_open=day_open,
                day_high=day_high,
                day_low=day_low,
                raw={"response_code": response_code},
            )

        if response_code == 5 and len(payload) >= 12:
            return None

        if response_code == 6 and len(payload) >= 16:
            return None

        if response_code == 8 and len(payload) >= 62:
            ltp = struct.unpack("<f", payload[8:12])[0]
            ltq = struct.unpack("<H", payload[12:14])[0]
            ltt_epoch = struct.unpack("<I", payload[14:18])[0]
            atp = struct.unpack("<f", payload[18:22])[0]
            volume = struct.unpack("<I", payload[22:26])[0]
            total_sell_qty = struct.unpack("<I", payload[26:30])[0]
            total_buy_qty = struct.unpack("<I", payload[30:34])[0]
            open_interest = struct.unpack("<I", payload[34:38])[0]
            day_open = struct.unpack("<f", payload[46:50])[0]
            prev_close = struct.unpack("<f", payload[50:54])[0]
            day_high = struct.unpack("<f", payload[54:58])[0]
            day_low = struct.unpack("<f", payload[58:62])[0]
            best_bid_quantity = 0
            best_ask_quantity = 0
            best_bid_price = 0.0
            best_ask_price = 0.0
            if len(payload) >= 82:
                best_bid_quantity = struct.unpack("<I", payload[62:66])[0]
                best_ask_quantity = struct.unpack("<I", payload[66:70])[0]
                best_bid_price = struct.unpack("<f", payload[74:78])[0]
                best_ask_price = struct.unpack("<f", payload[78:82])[0]
            return MarketTick(
                instrument=instrument,
                timestamp=self._decode_timestamp(ltt_epoch),
                ltp=ltp,
                ltq=ltq,
                ltt_epoch=ltt_epoch,
                atp=atp,
                volume=volume,
                total_buy_qty=total_buy_qty,
                total_sell_qty=total_sell_qty,
                open_interest=open_interest,
                day_open=day_open,
                day_high=day_high,
                day_low=day_low,
                prev_close=prev_close,
                best_bid_price=best_bid_price,
                best_ask_price=best_ask_price,
                best_bid_quantity=best_bid_quantity,
                best_ask_quantity=best_ask_quantity,
                raw={"response_code": response_code},
            )

        return None


async def stream_base_instruments(
    feed: DhanMarketFeed,
    instruments: list[MarketInstrument],
    on_tick,
) -> None:
    """Helper to connect the feed to a callback-driven consumer."""
    async for tick in feed.stream(instruments):
        await on_tick(tick)
