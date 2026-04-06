"""Trade-event persistence and attribution for the rebuilt NIFTY runtime."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from scripts.config import DATA_DIR
from scripts.log import get_logger
from scripts.schema import StructureProposal, TradeRecord


logger = get_logger("trade_recorder")


class TradeRecorder:
    """Builds and persists normalized trade records for analysis and reporting."""

    def __init__(self, *, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or (DATA_DIR / "records")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logger

    def build_trade_record(
        self,
        *,
        trade_id: str,
        state_at_entry: str,
        playbook: str,
        structure: StructureProposal,
        gross_pnl: float = 0.0,
        fees_and_costs: float = 0.0,
    ) -> TradeRecord:
        """Build a normalized trade record from the selected structure proposal."""
        return TradeRecord(
            trade_id=trade_id,
            state_at_entry=state_at_entry,
            playbook=playbook,
            structure_type=structure.structure_type,
            gross_pnl=gross_pnl,
            fees_and_costs=fees_and_costs,
            net_pnl=gross_pnl - fees_and_costs,
        )

    def append_trade_record(
        self,
        record: TradeRecord,
        *,
        session_date: str,
        underlying_context: dict[str, Any],
        expiry: str,
        strikes: tuple[float, ...],
        side: str,
        quantity: int,
        entry_price_or_prices: tuple[float, ...],
        exit_price_or_prices: tuple[float, ...],
        exit_reason: str,
    ) -> Path:
        """Append a fully attributed trade event to the session CSV file."""
        target = self.base_dir / f"trade_records_{session_date}.csv"
        payload = {
            **asdict(record),
            "session_date": session_date,
            "underlying_context": json.dumps(underlying_context, sort_keys=True),
            "expiry": expiry,
            "strike_or_strikes": json.dumps(list(strikes)),
            "side": side,
            "quantity": quantity,
            "entry_price_or_prices": json.dumps(list(entry_price_or_prices)),
            "exit_price_or_prices": json.dumps(list(exit_price_or_prices)),
            "exit_reason": exit_reason,
        }

        write_header = not target.exists()
        with target.open("a", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(payload.keys()))
            if write_header:
                writer.writeheader()
            writer.writerow(payload)

        self.logger.info(
            "TRADE_RECORDED | trade_id=%s session_date=%s playbook=%s structure=%s net_pnl=%s",
            record.trade_id,
            session_date,
            record.playbook,
            record.structure_type,
            record.net_pnl,
        )
        return target


def build_trade_record(
    *,
    trade_id: str,
    state_at_entry: str,
    playbook: str,
    structure: StructureProposal,
    gross_pnl: float = 0.0,
    fees_and_costs: float = 0.0,
) -> TradeRecord:
    """Convenience wrapper for one-shot trade-record construction."""
    return TradeRecorder().build_trade_record(
        trade_id=trade_id,
        state_at_entry=state_at_entry,
        playbook=playbook,
        structure=structure,
        gross_pnl=gross_pnl,
        fees_and_costs=fees_and_costs,
    )
