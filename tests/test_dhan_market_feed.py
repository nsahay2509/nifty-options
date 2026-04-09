from __future__ import annotations

import struct
from zoneinfo import ZoneInfo

import pytest

from scripts.brokers.dhan_market_feed import DhanMarketFeed
from scripts.brokers.types import BrokerCredentials
from scripts.schema import MarketInstrument


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
