"""Central configuration for the rebuilt NIFTY system."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
LOG_DIR = DATA_DIR / "logs"
MARKET_DATA_DIR = DATA_DIR / "market_data"


class ExecutionMode(StrEnum):
    PAPER = "paper"
    LIVE = "live"


class BrokerName(StrEnum):
    DHAN = "dhan"


class MarketFeedMode(StrEnum):
    TICKER = "ticker"
    QUOTE = "quote"
    FULL = "full"


class FuturesRolloverRule(StrEnum):
    NEAR_MONTH_UNTIL_EXPIRY = "near_month_until_expiry"
    NEXT_TRADING_DAY_AFTER_EXPIRY = "next_trading_day_after_expiry"


@dataclass(frozen=True)
class LoggingConfig:
    file: Path = LOG_DIR / "nifty_rebuild.log"


@dataclass(frozen=True)
class BrokerConfig:
    name: BrokerName = BrokerName.DHAN
    env_file: Path = Path("/home/ubuntu/nseo/.env")
    request_timeout_sec: int = 15
    instrument_master_file: Path = BASE_DIR / "archive" / "data" / "dhan_instruments.csv"


@dataclass(frozen=True)
class TradingConfig:
    execution_mode: ExecutionMode = ExecutionMode.PAPER
    live_trading_enabled: bool = False
    require_explicit_live_flag: bool = True
    # Consecutive 1-minute assessments required before entering/exiting on a state.
    # Current behavior clamps values below 1 up to 1, so 0 behaves the same as 1.
    entry_confirmations_required: int = 3
    exit_confirmations_required: int = 3


@dataclass(frozen=True)
class SessionConfig:
    market_timezone: str = "Asia/Kolkata"
    regular_open_hour: int = 9
    regular_open_minute: int = 15
    regular_close_hour: int = 15
    regular_close_minute: int = 30
    opening_range_minutes: int = 15
    weekly_expiry_weekday: int = 1


@dataclass(frozen=True)
class InstrumentConfig:
    name: str
    exchange_segment: str
    security_id: str = ""


@dataclass(frozen=True)
class MarketDataConfig:
    tick_store_dir: Path = MARKET_DATA_DIR / "ticks"
    candle_store_dir: Path = MARKET_DATA_DIR / "candles"
    base_feed_mode: MarketFeedMode = MarketFeedMode.QUOTE
    candle_interval_sec: int = 60
    derive_intervals_min: tuple[int, ...] = (1, 5, 15)
    use_index_for_structure: bool = True
    use_futures_for_volume: bool = True
    futures_rollover_rule: FuturesRolloverRule = FuturesRolloverRule.NEXT_TRADING_DAY_AFTER_EXPIRY
    futures_rollover_buffer_days: int = 0
    index_instrument: InstrumentConfig = InstrumentConfig(
        name="NIFTY_50_INDEX",
        exchange_segment="IDX_I",
        security_id="13",
    )
    futures_instrument: InstrumentConfig = InstrumentConfig(
        name="NIFTY_CURRENT_MONTH_FUT",
        exchange_segment="NSE_FNO",
        security_id="",
    )


@dataclass(frozen=True)
class AppConfig:
    logging: LoggingConfig = LoggingConfig()
    broker: BrokerConfig = BrokerConfig()
    session: SessionConfig = SessionConfig()
    trading: TradingConfig = TradingConfig()
    market_data: MarketDataConfig = MarketDataConfig()


APP_CONFIG = AppConfig()
