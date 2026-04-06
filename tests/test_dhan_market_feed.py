from __future__ import annotations

import struct
from zoneinfo import ZoneInfo

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
