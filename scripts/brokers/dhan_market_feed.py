"""Dhan WebSocket market-feed support for normalized tick streaming."""

from __future__ import annotations

import asyncio
import json
import struct
from dataclasses import dataclass
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


@dataclass(frozen=True)
class WatchdogAction:
    action: str
    security_ids: tuple[str, ...] = ()
    reason: str = ""


class SubscriptionWatchdog:
    """Detect stale subscriptions and recommend resubscribe or reconnect actions."""

    def __init__(
        self,
        *,
        critical_security_ids: set[str],
        stall_after_seconds: float = 90.0,
        resubscribe_cooldown_seconds: float = 30.0,
        reconnect_after_resubscribe_attempts: int = 2,
        reconnect_on_total_silence_seconds: float = 45.0,
    ) -> None:
        self.critical_security_ids = set(critical_security_ids)
        self.stall_after_seconds = max(float(stall_after_seconds), 1.0)
        self.resubscribe_cooldown_seconds = max(float(resubscribe_cooldown_seconds), 1.0)
        self.reconnect_after_resubscribe_attempts = max(int(reconnect_after_resubscribe_attempts), 1)
        self.reconnect_on_total_silence_seconds = max(float(reconnect_on_total_silence_seconds), 1.0)
        self.connected_at = 0.0
        self.last_seen_at: dict[str, float] = {}
        self.last_resubscribe_at: dict[str, float] = {}
        self.resubscribe_attempts: dict[str, int] = {}

    def reset(self, *, connected_at: float, security_ids: list[str]) -> None:
        self.connected_at = connected_at
        self.last_seen_at = {}
        self.last_resubscribe_at = {security_id: connected_at for security_id in security_ids}
        self.resubscribe_attempts = {security_id: 0 for security_id in security_ids}

    def observe_tick(self, security_id: str, *, now_monotonic: float) -> None:
        self.last_seen_at[security_id] = now_monotonic
        self.resubscribe_attempts[security_id] = 0

    def mark_resubscribe(self, security_ids: list[str], *, now_monotonic: float) -> None:
        for security_id in security_ids:
            self.last_resubscribe_at[security_id] = now_monotonic
            self.resubscribe_attempts[security_id] = self.resubscribe_attempts.get(security_id, 0) + 1

    def evaluate(self, *, now_monotonic: float, all_security_ids: list[str]) -> WatchdogAction:
        last_seen_values = [self.last_seen_at.get(security_id) for security_id in all_security_ids]
        seen_values = [value for value in last_seen_values if value is not None]
        if seen_values:
            latest_seen = max(seen_values)
            if now_monotonic - latest_seen >= self.reconnect_on_total_silence_seconds:
                return WatchdogAction(action="reconnect", reason="all_subscriptions_silent")
        elif now_monotonic - self.connected_at >= self.reconnect_on_total_silence_seconds:
            return WatchdogAction(action="reconnect", reason="no_ticks_after_connect")

        stale_critical: list[str] = []
        fresh_non_stale_exists = False
        for security_id in all_security_ids:
            last_seen_at = self.last_seen_at.get(security_id)
            if last_seen_at is None:
                stale = now_monotonic - self.connected_at >= self.stall_after_seconds
            else:
                stale = now_monotonic - last_seen_at >= self.stall_after_seconds
            if stale and security_id in self.critical_security_ids:
                stale_critical.append(security_id)
            elif not stale and last_seen_at is not None:
                fresh_non_stale_exists = True

        if not stale_critical or not fresh_non_stale_exists:
            return WatchdogAction(action="none")

        ready_to_resubscribe = [
            security_id
            for security_id in stale_critical
            if now_monotonic - self.last_resubscribe_at.get(security_id, self.connected_at)
            >= self.resubscribe_cooldown_seconds
        ]
        if not ready_to_resubscribe:
            return WatchdogAction(action="none")

        exhausted = [
            security_id
            for security_id in ready_to_resubscribe
            if self.resubscribe_attempts.get(security_id, 0) >= self.reconnect_after_resubscribe_attempts
        ]
        if exhausted:
            return WatchdogAction(
                action="reconnect",
                security_ids=tuple(exhausted),
                reason="critical_subscription_unrecovered",
            )

        return WatchdogAction(
            action="resubscribe",
            security_ids=tuple(ready_to_resubscribe),
            reason="critical_subscription_stalled",
        )


class DhanMarketFeed:
    """Thin websocket client that normalizes Dhan market feed into MarketTick objects."""

    def __init__(
        self,
        credentials: BrokerCredentials,
        *,
        mode: MarketFeedMode | None = None,
        watchdog_poll_seconds: float = 5.0,
        stall_after_seconds: float = 90.0,
        resubscribe_cooldown_seconds: float = 30.0,
        reconnect_after_resubscribe_attempts: int = 2,
        reconnect_on_total_silence_seconds: float = 45.0,
        reconnect_delay_seconds: float = 3.0,
    ) -> None:
        self.credentials = credentials
        self.mode = mode or APP_CONFIG.market_data.base_feed_mode
        self.market_timezone = ZoneInfo(APP_CONFIG.session.market_timezone)
        self.logger = get_logger("brokers.dhan_feed")
        self.watchdog_poll_seconds = max(float(watchdog_poll_seconds), 1.0)
        self.reconnect_delay_seconds = max(float(reconnect_delay_seconds), 0.5)
        self.stall_after_seconds = max(float(stall_after_seconds), 1.0)
        self.resubscribe_cooldown_seconds = max(float(resubscribe_cooldown_seconds), 1.0)
        self.reconnect_after_resubscribe_attempts = max(int(reconnect_after_resubscribe_attempts), 1)
        self.reconnect_on_total_silence_seconds = max(float(reconnect_on_total_silence_seconds), 1.0)

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
        loop = asyncio.get_running_loop()
        critical_security_ids = {
            instrument.security_id
            for instrument in instruments
            if instrument.instrument_type in {"INDEX", "FUTURES"}
        }
        watchdog = SubscriptionWatchdog(
            critical_security_ids=critical_security_ids,
            stall_after_seconds=self.stall_after_seconds,
            resubscribe_cooldown_seconds=self.resubscribe_cooldown_seconds,
            reconnect_after_resubscribe_attempts=self.reconnect_after_resubscribe_attempts,
            reconnect_on_total_silence_seconds=self.reconnect_on_total_silence_seconds,
        )
        all_security_ids = [instrument.security_id for instrument in instruments]

        while True:
            try:
                async with websockets.connect(self.websocket_url(), ping_interval=10, ping_timeout=40) as ws:
                    connected_at = loop.time()
                    watchdog.reset(connected_at=connected_at, security_ids=all_security_ids)
                    for subscription_payload in self._subscription_messages(instruments):
                        await ws.send(subscription_payload)
                    self.logger.info("MARKET_FEED_CONNECTED | instruments=%s mode=%s", len(instruments), self.mode.value)
                    next_watchdog_check_at = connected_at + self.watchdog_poll_seconds

                    async def run_watchdog(now_monotonic: float) -> bool:
                        action = watchdog.evaluate(now_monotonic=now_monotonic, all_security_ids=all_security_ids)
                        if action.action == "resubscribe":
                            target_instruments = [
                                instrument_map[security_id]
                                for security_id in action.security_ids
                                if security_id in instrument_map
                            ]
                            if target_instruments:
                                for subscription_payload in self._subscription_messages(target_instruments):
                                    await ws.send(subscription_payload)
                                watchdog.mark_resubscribe(
                                    [instrument.security_id for instrument in target_instruments],
                                    now_monotonic=loop.time(),
                                )
                                self.logger.warning(
                                    "MARKET_FEED_RESUBSCRIBE | reason=%s security_ids=%s instruments=%s",
                                    action.reason,
                                    ",".join(action.security_ids),
                                    ",".join(instrument.name for instrument in target_instruments),
                                )
                            return False
                        if action.action == "reconnect":
                            self.logger.warning(
                                "MARKET_FEED_RECONNECT | reason=%s security_ids=%s",
                                action.reason,
                                ",".join(action.security_ids),
                            )
                            return True
                        return False

                    while True:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=self.watchdog_poll_seconds)
                        except asyncio.TimeoutError:
                            if await run_watchdog(loop.time()):
                                break
                            next_watchdog_check_at = loop.time() + self.watchdog_poll_seconds
                            continue

                        if isinstance(raw, str):
                            self.logger.info("MARKET_FEED_TEXT | payload=%s", raw)
                            now_monotonic = loop.time()
                            if now_monotonic >= next_watchdog_check_at:
                                if await run_watchdog(now_monotonic):
                                    break
                                next_watchdog_check_at = now_monotonic + self.watchdog_poll_seconds
                            continue

                        tick = self._parse_binary(raw, instrument_map)
                        if tick is not None:
                            watchdog.observe_tick(tick.instrument.security_id, now_monotonic=loop.time())
                            now_monotonic = loop.time()
                            if now_monotonic >= next_watchdog_check_at:
                                if await run_watchdog(now_monotonic):
                                    break
                                next_watchdog_check_at = now_monotonic + self.watchdog_poll_seconds
                            yield tick
            except Exception as exc:
                self.logger.warning("MARKET_FEED_CONNECTION_ERROR | reason=%s", exc)

            self.logger.info("MARKET_FEED_RECONNECT_DELAY | seconds=%.1f", self.reconnect_delay_seconds)
            await asyncio.sleep(self.reconnect_delay_seconds)

    def _subscription_message(self, instruments: list[MarketInstrument]) -> str:
        return self._subscription_message_for_mode(instruments, mode=self.mode)

    def _mode_for_instrument(self, instrument: MarketInstrument) -> MarketFeedMode:
        # Dhan can omit index packets in FULL mode; keep index on QUOTE for reliability.
        if self.mode == MarketFeedMode.FULL and instrument.instrument_type == "INDEX":
            return MarketFeedMode.QUOTE
        return self.mode

    def _subscription_messages(self, instruments: list[MarketInstrument]) -> list[str]:
        grouped: dict[MarketFeedMode, list[MarketInstrument]] = {}
        for instrument in instruments:
            mode = self._mode_for_instrument(instrument)
            grouped.setdefault(mode, []).append(instrument)
        return [
            self._subscription_message_for_mode(grouped_instruments, mode=mode)
            for mode, grouped_instruments in grouped.items()
            if grouped_instruments
        ]

    def _subscription_message_for_mode(self, instruments: list[MarketInstrument], *, mode: MarketFeedMode) -> str:
        payload = {
            "RequestCode": REQUEST_CODE_BY_MODE[mode],
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
