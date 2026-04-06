from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from scripts.app_config import APP_CONFIG
from scripts.paper_trade_engine_core import BasePaperTradeEngine


@dataclass(frozen=True)
class TradeEngineSpec:
    side: str
    logger: object
    open_position_file_getter: Callable[[], Path]
    pnl_file_getter: Callable[[], Path]
    trade_events_file_getter: Callable[[], Path]
    recovery_message: str
    recovery_error_code: str
    stale_position_message: str
    stale_position_check_error_code: str
    reset_message_template: str
    entry_invalid_regime_message: str | None = None


def build_engine_class(spec: TradeEngineSpec):
    class ConfiguredPaperTradeEngine(BasePaperTradeEngine):
        logger = spec.logger
        recovery_message = spec.recovery_message
        recovery_error_code = spec.recovery_error_code
        stale_position_message = spec.stale_position_message
        stale_position_check_error_code = spec.stale_position_check_error_code
        entry_invalid_regime_message = spec.entry_invalid_regime_message

        def get_open_position_file(self) -> Path:
            return spec.open_position_file_getter()

        def get_pnl_file(self) -> Path:
            return spec.pnl_file_getter()

        def get_trade_events_file(self) -> Path:
            return spec.trade_events_file_getter()

        def get_side(self) -> str:
            return spec.side

        def get_reset_log_message(self, old_date, new_date) -> str:
            return spec.reset_message_template.format(old_date=old_date, new_date=new_date)

        def format_entry_message(
            self,
            regime: str,
            spot: float,
            atm: dict,
            ce_id: int | None,
            pe_id: int | None,
        ) -> str:
            if spec.side == "BUY":
                entry_label = f"BUY_FROM_{regime}"
            else:
                entry_label = regime

            return (
                f"ENTRY | {entry_label} | spot={spot:.2f} "
                f"strike={atm['strike']} exp={atm['expiry']} "
                f"ce_id={ce_id} pe_id={pe_id} lots={APP_CONFIG.trade.lots}"
            )

        def resolve_entry_ids(self, regime: str, atm: dict) -> tuple[int | None, int | None]:
            if spec.side == "SELL":
                ce_id = None
                pe_id = None

                if regime == "SELL_PE":
                    pe_id = atm["pe_security_id"]
                elif regime == "SELL_CE":
                    ce_id = atm["ce_security_id"]

                return ce_id, pe_id

            if regime == "SELL_PE":
                return atm["ce_security_id"], None
            return None, atm["pe_security_id"]

        def compute_leg_pnl(self, entry: float, ltp: float, qty: int) -> float:
            if spec.side == "SELL":
                return (entry - ltp) * qty
            return (ltp - entry) * qty

    return ConfiguredPaperTradeEngine
