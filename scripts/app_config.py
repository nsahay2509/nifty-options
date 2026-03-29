from dataclasses import dataclass
from datetime import time as dtime
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class EvaluatorConfig:
    start_time: dtime = dtime(9, 15)
    end_time: dtime = dtime(15, 30)
    run_delay_sec: int = 5


@dataclass(frozen=True)
class SignalConfig:
    min_gap_minutes: int = 10
    regime_persistence: int = 2


@dataclass(frozen=True)
class RegimeConfig:
    window: int = 25
    min_trade_time: tuple[int, int] = (9, 20)
    enable_straddle: bool = False
    straddle_d_max: float = 0.30
    straddle_comp_max: float = 0.95
    trend_d_min: float = 0.32
    use_range_guard: bool = True
    max_window_range_points: float = 180.0


@dataclass(frozen=True)
class TradeConfig:
    start_scan: dtime = dtime(9, 20)
    no_new_entry_after: dtime = dtime(15, 15)
    force_exit_time: dtime = dtime(15, 25)
    window: int = 25
    cooldown_minutes: int = 5
    lots: int = 1
    min_hold_minutes: int = 3
    max_trade_loss: float = 600.0
    profit_trail_arm: float = 400.0
    profit_trail_giveback: float = 250.0
    reentry_block_minutes: int = 15
    reentry_min_d_improvement: float = 0.05
    lot_size: int = 50


@dataclass(frozen=True)
class ReportingConfig:
    trade_cost: int = 100


@dataclass(frozen=True)
class AppConfig:
    evaluator: EvaluatorConfig = EvaluatorConfig()
    signal: SignalConfig = SignalConfig()
    regime: RegimeConfig = RegimeConfig()
    trade: TradeConfig = TradeConfig()
    reporting: ReportingConfig = ReportingConfig()


APP_CONFIG = AppConfig()
