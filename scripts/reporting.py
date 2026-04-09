"""State-wise and playbook-wise reporting for the rebuilt NIFTY runtime."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from scripts.config import DATA_DIR
from scripts.log import get_logger


logger = get_logger("reporting")


class ReportingService:
    """Builds session summaries from normalized trade-record files."""

    def __init__(self, *, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir or (DATA_DIR / "reports")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logger

    def summarize_trade_file(self, trade_file: Path) -> dict[str, Any]:
        """Summarize one trade record CSV into aggregate state and playbook views."""
        with trade_file.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))

        summary: dict[str, Any] = {
            "session_date": self._extract_session_date(trade_file, rows),
            "total_trades": len(rows),
            "gross_pnl": 0.0,
            "fees_and_costs": 0.0,
            "net_pnl": 0.0,
            "by_state": {},
            "by_playbook": {},
        }

        for row in rows:
            gross = self._safe_float(row.get("gross_pnl", 0.0))
            costs = self._safe_float(row.get("fees_and_costs", 0.0))
            net = self._safe_float(row.get("net_pnl", 0.0))
            state = str(row.get("state_at_entry", "") or "")
            playbook = str(row.get("playbook", "") or "")

            summary["gross_pnl"] += gross
            summary["fees_and_costs"] += costs
            summary["net_pnl"] += net

            self._update_bucket(summary["by_state"], state, gross, costs, net)
            self._update_bucket(summary["by_playbook"], playbook, gross, costs, net)

        self.logger.info(
            "REPORT_SUMMARY | session_date=%s total_trades=%s net_pnl=%s",
            summary["session_date"],
            summary["total_trades"],
            summary["net_pnl"],
        )
        return summary

    def write_summary(self, trade_file: Path) -> Path:
        """Persist the computed session summary as a JSON report."""
        summary = self.summarize_trade_file(trade_file)
        session_date = summary["session_date"] or "unknown_session"
        target = self.output_dir / f"trade_summary_{session_date}.json"
        with target.open("w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2, sort_keys=True)
        self.logger.info("REPORT_WRITTEN | path=%s", target)
        return target

    @staticmethod
    def _extract_session_date(trade_file: Path, rows: list[dict[str, str]]) -> str:
        if rows:
            return rows[0].get("session_date", "")
        stem = trade_file.stem.replace("trade_records_", "")
        return stem

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _update_bucket(bucket: dict[str, dict[str, float]], key: str, gross: float, costs: float, net: float) -> None:
        if key not in bucket:
            bucket[key] = {"count": 0, "gross_pnl": 0.0, "fees_and_costs": 0.0, "net_pnl": 0.0}
        bucket[key]["count"] += 1
        bucket[key]["gross_pnl"] += gross
        bucket[key]["fees_and_costs"] += costs
        bucket[key]["net_pnl"] += net


def summarize_trade_file(trade_file: Path) -> dict[str, Any]:
    """Convenience wrapper for one-shot summary generation."""
    return ReportingService().summarize_trade_file(trade_file)
