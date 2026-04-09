from __future__ import annotations

import asyncio
import json
import struct
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import scripts.brokers.dhan_market_feed as dhan_market_feed
from scripts.config import MarketFeedMode
from scripts.brokers.dhan_market_feed import DhanMarketFeed, SubscriptionWatchdog
from scripts.brokers.types import BrokerCredentials
from scripts.schema import MarketInstrument, MarketTick


def test_quote_tick_timestamp_is_normalized_to_market_timezone() -> None:
    feed = DhanMarketFeed(BrokerCredentials(client_id="demo", access_token="demo"))
    instrument = MarketInstrument(
        name="NIFTY_50_INDEX",
        exchange_segment="IDX_I",
        security_id="13",
        instrument_type="INDEX",
    )

    payload = bytearray(50)
    payload[0] = 4
    payload[3] = 13
    payload[4:8] = struct.pack("<I", 13)
    payload[8:12] = struct.pack("<f", 22659.05)
    payload[12:14] = struct.pack("<H", 1)
    payload[14:18] = struct.pack("<I", 1775476092)
    payload[18:22] = struct.pack("<f", 22658.5)
    payload[22:26] = struct.pack("<I", 100)
    payload[26:30] = struct.pack("<I", 10)
    payload[30:34] = struct.pack("<I", 12)
    payload[34:38] = struct.pack("<f", 22500.0)
    payload[42:46] = struct.pack("<f", 22700.0)
    payload[46:50] = struct.pack("<f", 22400.0)

    tick = feed._parse_binary(bytes(payload), {"13": instrument})

    assert tick is not None
    assert tick.timestamp.tzinfo == ZoneInfo("Asia/Kolkata")
    assert tick.timestamp.hour == 11
    assert tick.timestamp.minute == 48


def test_full_tick_parses_top_of_book_depth() -> None:
    feed = DhanMarketFeed(BrokerCredentials(client_id="demo", access_token="demo"))
    instrument = MarketInstrument(
        name="NIFTY_26_MAY_23850_PUT",
        exchange_segment="NSE_FNO",
        security_id="72174",
        instrument_type="OPTION",
    )

    payload = bytearray(82)
    payload[0] = 8
    payload[3] = 2
    payload[4:8] = struct.pack("<I", 72174)
    payload[8:12] = struct.pack("<f", 551.0)
    payload[12:14] = struct.pack("<H", 390)
    payload[14:18] = struct.pack("<I", 1775701010)
    payload[18:22] = struct.pack("<f", 545.0)
    payload[22:26] = struct.pack("<I", 4745)
    payload[26:30] = struct.pack("<I", 120)
    payload[30:34] = struct.pack("<I", 140)
    payload[34:38] = struct.pack("<I", 3200)
    payload[46:50] = struct.pack("<f", 504.4)
    payload[50:54] = struct.pack("<f", 520.1)
    payload[54:58] = struct.pack("<f", 576.85)
    payload[58:62] = struct.pack("<f", 495.2)
    payload[62:66] = struct.pack("<I", 250)
    payload[66:70] = struct.pack("<I", 300)
    payload[74:78] = struct.pack("<f", 550.5)
    payload[78:82] = struct.pack("<f", 551.5)

    tick = feed._parse_binary(bytes(payload), {"72174": instrument})

    assert tick is not None
    assert tick.best_bid_quantity == 250
    assert tick.best_ask_quantity == 300
    assert tick.best_bid_price == 550.5
    assert tick.best_ask_price == 551.5
    assert tick.prev_close == pytest.approx(520.1)


def test_watchdog_resubscribes_stale_index_when_other_streams_are_alive() -> None:
    watchdog = SubscriptionWatchdog(
        critical_security_ids={"13", "66691"},
        stall_after_seconds=90,
        resubscribe_cooldown_seconds=30,
        reconnect_after_resubscribe_attempts=2,
        reconnect_on_total_silence_seconds=45,
    )
    watchdog.reset(connected_at=0.0, security_ids=["13", "66691", "72174"])
    watchdog.observe_tick("13", now_monotonic=10.0)
    watchdog.observe_tick("66691", now_monotonic=110.0)
    watchdog.observe_tick("72174", now_monotonic=110.0)

    action = watchdog.evaluate(now_monotonic=120.0, all_security_ids=["13", "66691", "72174"])

    assert action.action == "resubscribe"
    assert action.security_ids == ("13",)
    assert action.reason == "critical_subscription_stalled"


def test_watchdog_reconnects_when_resubscribe_does_not_recover_stale_index() -> None:
    watchdog = SubscriptionWatchdog(
        critical_security_ids={"13", "66691"},
        stall_after_seconds=90,
        resubscribe_cooldown_seconds=30,
        reconnect_after_resubscribe_attempts=2,
        reconnect_on_total_silence_seconds=45,
    )
    watchdog.reset(connected_at=0.0, security_ids=["13", "66691", "72174"])
    watchdog.observe_tick("13", now_monotonic=10.0)
    watchdog.observe_tick("66691", now_monotonic=110.0)
    watchdog.observe_tick("72174", now_monotonic=110.0)
    watchdog.mark_resubscribe(["13"], now_monotonic=120.0)
    watchdog.mark_resubscribe(["13"], now_monotonic=151.0)
    watchdog.observe_tick("66691", now_monotonic=181.0)
    watchdog.observe_tick("72174", now_monotonic=181.0)

    action = watchdog.evaluate(now_monotonic=182.0, all_security_ids=["13", "66691", "72174"])

    assert action.action == "reconnect"
    assert action.security_ids == ("13",)
    assert action.reason == "critical_subscription_unrecovered"


def test_watchdog_reconnects_after_total_silence() -> None:
    watchdog = SubscriptionWatchdog(
        critical_security_ids={"13", "66691"},
        stall_after_seconds=90,
        resubscribe_cooldown_seconds=30,
        reconnect_after_resubscribe_attempts=2,
        reconnect_on_total_silence_seconds=45,
    )
    watchdog.reset(connected_at=0.0, security_ids=["13", "66691"])
    watchdog.observe_tick("13", now_monotonic=5.0)
    watchdog.observe_tick("66691", now_monotonic=7.0)

    action = watchdog.evaluate(now_monotonic=53.0, all_security_ids=["13", "66691"])

    assert action.action == "reconnect"
    assert action.reason == "all_subscriptions_silent"


def test_stream_runs_watchdog_checks_even_when_ticks_are_continuous(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeLoop:
        def __init__(self) -> None:
            self.now = 0.0

        def time(self) -> float:
            return self.now

    class FakeWebSocket:
        def __init__(self, loop: FakeLoop) -> None:
            self._loop = loop
            self.sent_messages: list[str] = []

        async def send(self, payload: str) -> None:
            self.sent_messages.append(payload)

        async def recv(self) -> bytes:
            # Keep the feed busy so watchdog timeouts never fire.
            self._loop.now += 0.6
            return b"tick"

    class FakeConnectContext:
        def __init__(self, ws: FakeWebSocket) -> None:
            self._ws = ws

        async def __aenter__(self) -> FakeWebSocket:
            return self._ws

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

    class FakeWebsocketsModule:
        def __init__(self, ws: FakeWebSocket) -> None:
            self._ws = ws

        def connect(self, *_args, **_kwargs):
            return FakeConnectContext(self._ws)

    fake_loop = FakeLoop()
    fake_ws = FakeWebSocket(fake_loop)
    monkeypatch.setattr(dhan_market_feed.asyncio, "get_running_loop", lambda: fake_loop)
    monkeypatch.setattr(dhan_market_feed, "websockets", FakeWebsocketsModule(fake_ws))

    index_inst = MarketInstrument(name="NIFTY_50_INDEX", exchange_segment="IDX_I", security_id="13", instrument_type="INDEX")
    futures_inst = MarketInstrument(
        name="NIFTY_CURRENT_MONTH_FUT",
        exchange_segment="NSE_FNO",
        security_id="66691",
        instrument_type="FUTURES",
    )
    option_inst = MarketInstrument(
        name="NIFTY_26_MAY_23850_PUT",
        exchange_segment="NSE_FNO",
        security_id="72174",
        instrument_type="OPTION",
    )

    feed = DhanMarketFeed(BrokerCredentials(client_id="demo", access_token="demo"))
    feed.watchdog_poll_seconds = 0.5
    feed.stall_after_seconds = 1.0
    feed.resubscribe_cooldown_seconds = 1.0

    def _fake_parse_binary(_payload: bytes, _instrument_map: dict[str, MarketInstrument]) -> MarketTick:
        return MarketTick(
            instrument=option_inst,
            timestamp=datetime.now(ZoneInfo("Asia/Kolkata")),
            ltp=100.0,
        )

    monkeypatch.setattr(feed, "_parse_binary", _fake_parse_binary)

    async def _run_stream_until_resubscribe() -> None:
        stream = feed.stream([index_inst, futures_inst, option_inst])
        try:
            for _ in range(8):
                await asyncio.wait_for(anext(stream), timeout=0.2)
                if len(fake_ws.sent_messages) >= 3:
                    break
        finally:
            await stream.aclose()

    asyncio.run(_run_stream_until_resubscribe())

    assert len(fake_ws.sent_messages) >= 3
    all_payloads = [json.loads(payload) for payload in fake_ws.sent_messages]
    # We should eventually attempt an index-only re-subscribe once index is stale.
    assert any(
        payload.get("RequestCode") == 17
        and [item["SecurityId"] for item in payload.get("InstrumentList", [])] == ["13"]
        for payload in all_payloads
    )


def test_subscription_messages_route_index_to_quote_when_base_mode_full() -> None:
    feed = DhanMarketFeed(BrokerCredentials(client_id="demo", access_token="demo"))
    feed.mode = MarketFeedMode.FULL

    index_inst = MarketInstrument(name="NIFTY_50_INDEX", exchange_segment="IDX_I", security_id="13", instrument_type="INDEX")
    fut_inst = MarketInstrument(
        name="NIFTY_CURRENT_MONTH_FUT",
        exchange_segment="NSE_FNO",
        security_id="66691",
        instrument_type="FUTURES",
    )

    payloads = [json.loads(payload) for payload in feed._subscription_messages([index_inst, fut_inst])]

    assert len(payloads) == 2
    request_codes = {payload["RequestCode"] for payload in payloads}
    assert request_codes == {17, 21}

    quote_payload = next(payload for payload in payloads if payload["RequestCode"] == 17)
    full_payload = next(payload for payload in payloads if payload["RequestCode"] == 21)
    assert [item["SecurityId"] for item in quote_payload["InstrumentList"]] == ["13"]
    assert [item["SecurityId"] for item in full_payload["InstrumentList"]] == ["66691"]
