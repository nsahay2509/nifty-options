"""Trade-event persistence and attribution for the rebuilt NIFTY runtime."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts.config import DATA_DIR
from scripts.log import get_logger
from scripts.schema import StructureProposal, TradeRecord


logger = get_logger("trade_recorder")
IST = ZoneInfo("Asia/Kolkata")
TRADE_RECORD_FIELDNAMES = [
    "trade_id",
    "status",
    "opened_at",
    "closed_at",
    "holding_minutes",
    "state_at_entry",
    "playbook",
    "structure_type",
    "trade_bias",
    "entry_reason",
    "gross_pnl",
    "fees_and_costs",
    "net_pnl",
    "realised_pnl",
    "unrealised_pnl",
    "session_date",
    "underlying_context",
    "underlying_entry_price",
    "underlying_exit_price",
    "expiry",
    "strike_or_strikes",
    "side",
    "quantity",
    "entry_price_or_prices",
    "exit_price_or_prices",
    "entry_credit",
    "entry_debit",
    "exit_close_value",
    "leg_count",
    "option_types",
    "leg_symbols",
    "legs_json",
    "exit_reason",
]
LEGACY_TRADE_RECORD_FIELDNAMES = [
    "trade_id",
    "state_at_entry",
    "playbook",
    "structure_type",
    "gross_pnl",
    "fees_and_costs",
    "net_pnl",
    "session_date",
    "underlying_context",
    "expiry",
    "strike_or_strikes",
    "side",
    "quantity",
    "entry_price_or_prices",
    "exit_price_or_prices",
    "exit_reason",
]


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
        status: str = "OPEN",
        opened_at: str = "",
        closed_at: str = "",
        entry_reason: str = "",
        trade_bias: str = "",
        underlying_exit_price: float | None = None,
        entry_credit: float = 0.0,
        entry_debit: float = 0.0,
        exit_close_value: float = 0.0,
        realised_pnl: float | None = None,
        unrealised_pnl: float = 0.0,
        legs: list[dict[str, Any]] | None = None,
    ) -> Path:
        """Append a fully attributed trade event to the session CSV file."""
        target = self.base_dir / f"trade_records_{session_date}.csv"
        normalised_legs = self._normalise_legs(
            legs or self._infer_legs(structure_type=record.structure_type, strikes=strikes, quantity=quantity),
            opened_at=opened_at,
            closed_at=closed_at,
        )

        if target.exists():
            self._normalize_file_if_needed(target)

        payload = self._ensure_schema(
            {
                **asdict(record),
                "status": status,
                "opened_at": opened_at,
                "closed_at": closed_at,
                "trade_bias": trade_bias or self._infer_trade_bias(record.playbook, record.structure_type, normalised_legs),
                "entry_reason": entry_reason,
                "realised_pnl": realised_pnl if realised_pnl is not None else record.net_pnl,
                "unrealised_pnl": unrealised_pnl,
                "session_date": session_date,
                "underlying_context": underlying_context,
                "underlying_entry_price": underlying_context.get("underlying_price", 0.0),
                "underlying_exit_price": underlying_exit_price,
                "expiry": expiry,
                "strike_or_strikes": list(strikes),
                "side": side,
                "quantity": quantity,
                "entry_price_or_prices": list(entry_price_or_prices),
                "exit_price_or_prices": list(exit_price_or_prices),
                "entry_credit": entry_credit,
                "entry_debit": entry_debit,
                "exit_close_value": exit_close_value,
                "legs_json": normalised_legs,
                "exit_reason": exit_reason,
            }
        )

        write_header = not target.exists()
        with target.open("a", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=TRADE_RECORD_FIELDNAMES)
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

    def finalize_trade_record(
        self,
        *,
        trade_id: str,
        session_date: str,
        gross_pnl: float,
        fees_and_costs: float = 0.0,
        exit_price_or_prices: tuple[float, ...] = (),
        exit_reason: str | None = None,
        closed_at: str | None = None,
        underlying_exit_price: float | None = None,
        exit_close_value: float | None = None,
        unrealised_pnl: float = 0.0,
        legs: list[dict[str, Any]] | None = None,
    ) -> Path | None:
        """Update a previously recorded trade row with its realised P&L when the trade closes."""
        target = self.base_dir / f"trade_records_{session_date}.csv"
        if not target.exists():
            self.logger.warning("TRADE_FINALIZE_MISSING | trade_id=%s session_date=%s", trade_id, session_date)
            return None

        with target.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            rows = [self._ensure_schema(dict(row)) for row in reader]

        if not rows:
            self.logger.warning("TRADE_FINALIZE_EMPTY | trade_id=%s session_date=%s", trade_id, session_date)
            return None

        updated = False
        gross = round(float(gross_pnl or 0.0), 2)
        costs = round(float(fees_and_costs or 0.0), 2)
        net = round(gross - costs, 2)

        for index, row in enumerate(rows):
            if row.get("trade_id") != trade_id:
                continue

            row["gross_pnl"] = gross
            row["fees_and_costs"] = costs
            row["net_pnl"] = net
            row["realised_pnl"] = gross
            row["unrealised_pnl"] = round(float(unrealised_pnl or 0.0), 2)
            row["status"] = "CLOSED"
            if exit_reason is not None:
                row["exit_reason"] = exit_reason
            if exit_price_or_prices:
                row["exit_price_or_prices"] = list(exit_price_or_prices)
            if closed_at is not None:
                row["closed_at"] = closed_at
            if underlying_exit_price is not None:
                row["underlying_exit_price"] = float(underlying_exit_price)
            if exit_close_value is not None:
                row["exit_close_value"] = float(exit_close_value)
            if legs is not None:
                row["legs_json"] = self._normalise_legs(legs, opened_at=str(row.get("opened_at", "")), closed_at=closed_at or str(row.get("closed_at", "")))

            rows[index] = self._ensure_schema(row)
            updated = True
            break

        if not updated:
            self.logger.warning("TRADE_FINALIZE_NOT_FOUND | trade_id=%s session_date=%s", trade_id, session_date)
            return None

        with target.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=TRADE_RECORD_FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)

        self.logger.info(
            "TRADE_FINALIZED | trade_id=%s session_date=%s gross_pnl=%s net_pnl=%s",
            trade_id,
            session_date,
            gross,
            net,
        )
        return target

    def normalize_trade_file(self, *, session_date: str) -> Path | None:
        """Rewrite a session CSV into the full enriched schema, filling derivable defaults."""
        target = self.base_dir / f"trade_records_{session_date}.csv"
        if not target.exists():
            return None

        with target.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            rows = [self._ensure_schema(dict(row)) for row in reader]

        with target.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=TRADE_RECORD_FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)

        self.logger.info("TRADE_FILE_NORMALIZED | session_date=%s rows=%s", session_date, len(rows))
        return target

    def _ensure_schema(self, row: dict[str, Any]) -> dict[str, str]:
        row = self._repair_misaligned_row(dict(row))
        payload = {field: self._stringify_value(row.get(field, "")) for field in TRADE_RECORD_FIELDNAMES}

        payload["underlying_context"] = self._stringify_json(row.get("underlying_context", {}), default={})
        payload["strike_or_strikes"] = self._stringify_json(row.get("strike_or_strikes", []), default=[])
        payload["entry_price_or_prices"] = self._stringify_json(row.get("entry_price_or_prices", []), default=[])
        payload["exit_price_or_prices"] = self._stringify_json(row.get("exit_price_or_prices", []), default=[])

        if not payload["opened_at"]:
            inferred_open = self._infer_opened_at(payload["trade_id"])
            if inferred_open:
                payload["opened_at"] = inferred_open

        if not payload["underlying_entry_price"]:
            try:
                context = json.loads(payload["underlying_context"]) if payload["underlying_context"] else {}
                if isinstance(context, dict) and context.get("underlying_price") is not None:
                    payload["underlying_entry_price"] = str(float(context.get("underlying_price", 0.0)))
            except Exception:
                payload["underlying_entry_price"] = "0.0"

        for numeric_field in (
            "gross_pnl",
            "fees_and_costs",
            "net_pnl",
            "realised_pnl",
            "unrealised_pnl",
            "underlying_entry_price",
            "entry_credit",
            "entry_debit",
            "exit_close_value",
        ):
            if payload[numeric_field] == "":
                payload[numeric_field] = "0.0"
                continue
            try:
                payload[numeric_field] = str(float(payload[numeric_field]))
            except (TypeError, ValueError):
                payload[numeric_field] = "0.0"

        if not payload["status"]:
            payload["status"] = "CLOSED" if payload["closed_at"] else "OPEN"

        if not payload["entry_reason"]:
            payload["entry_reason"] = f"state:{payload['state_at_entry']} | playbook:{payload['playbook']}".strip()

        entry_prices = self._parse_json_value(payload["entry_price_or_prices"], default=[])
        entry_total = round(sum(float(price or 0.0) for price in entry_prices), 2) if isinstance(entry_prices, list) else 0.0
        credit_structures = {"iron_condor", "call_or_put_credit_spread", "defined_risk_credit_spread"}
        if payload["entry_credit"] == "0.0" and payload["entry_debit"] == "0.0" and entry_total > 0:
            if payload["structure_type"] in credit_structures:
                payload["entry_credit"] = str(entry_total)
            else:
                payload["entry_debit"] = str(entry_total)

        holding_minutes = self._compute_holding_minutes(payload["opened_at"], payload["closed_at"])
        payload["holding_minutes"] = "" if holding_minutes is None else str(holding_minutes)

        legs_source = row.get("legs_json", [])
        normalised_legs = self._normalise_legs(
            self._parse_json_value(legs_source, default=[])
            or self._infer_legs(
                structure_type=payload["structure_type"],
                strikes=tuple(self._parse_json_value(payload["strike_or_strikes"], default=[])),
                quantity=self._safe_int(payload["quantity"], default=1),
            ),
            opened_at=payload["opened_at"],
            closed_at=payload["closed_at"],
        )
        payload["legs_json"] = self._stringify_json(normalised_legs, default=[])
        payload["leg_count"] = str(len(normalised_legs))
        payload["option_types"] = self._stringify_json(sorted({str(leg.get("option_type", "")) for leg in normalised_legs if leg.get("option_type")}), default=[])
        payload["leg_symbols"] = self._stringify_json([str(leg.get("symbol", "")) for leg in normalised_legs if leg.get("symbol")], default=[])

        if not payload["trade_bias"]:
            payload["trade_bias"] = self._infer_trade_bias(payload["playbook"], payload["structure_type"], normalised_legs)

        return payload

    def _normalize_file_if_needed(self, target: Path) -> None:
        try:
            with target.open(encoding="utf-8", newline="") as fh:
                header = fh.readline().strip()
        except Exception:
            return

        expected_header = ",".join(TRADE_RECORD_FIELDNAMES)
        if header == expected_header:
            return

        with target.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            rows = [self._ensure_schema(dict(row)) for row in reader]

        with target.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=TRADE_RECORD_FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)

        self.logger.info("TRADE_FILE_NORMALIZED | path=%s rows=%s", target, len(rows))

    @staticmethod
    def _repair_misaligned_row(row: dict[str, Any]) -> dict[str, Any]:
        extras = row.get(None)
        if not isinstance(extras, list) or not extras:
            row.pop(None, None)
            return row

        ordered_keys = [key for key in row.keys() if key is not None]
        values = [row.get(key, "") for key in ordered_keys] + list(extras)

        if len(values) == len(TRADE_RECORD_FIELDNAMES):
            return {field: values[index] for index, field in enumerate(TRADE_RECORD_FIELDNAMES)}

        if len(values) == len(LEGACY_TRADE_RECORD_FIELDNAMES):
            return {field: values[index] for index, field in enumerate(LEGACY_TRADE_RECORD_FIELDNAMES)}

        row.pop(None, None)
        return row

    def _normalise_legs(
        self,
        legs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        *,
        opened_at: str = "",
        closed_at: str = "",
    ) -> list[dict[str, Any]]:
        normalised: list[dict[str, Any]] = []
        for leg in legs:
            if not isinstance(leg, dict):
                continue
            strike = float(leg.get("strike", 0.0) or 0.0)
            option_type = str(leg.get("option_type", "") or "").upper()
            side = str(leg.get("side", "") or "")
            item = {
                "symbol": str(leg.get("symbol", "") or self._format_leg_symbol(strike, option_type)),
                "security_id": str(leg.get("security_id", "") or ""),
                "strike": strike,
                "option_type": option_type,
                "side": side,
                "quantity": self._safe_int(leg.get("quantity", 1), default=1),
                "lot_size": self._safe_int(leg.get("lot_size", 0), default=0),
                "entry_price": self._safe_float_or_none(leg.get("entry_price")),
                "last_price": self._safe_float_or_none(leg.get("last_price")),
                "entry_time": str(leg.get("entry_time", "") or opened_at),
                "exit_time": str(leg.get("exit_time", "") or closed_at),
            }
            normalised.append(item)
        return normalised

    def _infer_legs(self, *, structure_type: str, strikes: tuple[float, ...], quantity: int) -> list[dict[str, Any]]:
        strikes = tuple(float(strike) for strike in strikes)
        if not strikes:
            return []

        if structure_type == "iron_condor" and len(strikes) == 4:
            low_wing, low_short, high_short, high_wing = strikes
            return [
                self._build_leg(low_wing, "PE", "BUY", quantity),
                self._build_leg(low_short, "PE", "SELL", quantity),
                self._build_leg(high_short, "CE", "SELL", quantity),
                self._build_leg(high_wing, "CE", "BUY", quantity),
            ]

        if structure_type in {"call_or_put_credit_spread", "defined_risk_credit_spread"} and len(strikes) == 2:
            long_strike, short_strike = strikes
            return [
                self._build_leg(long_strike, "PE", "BUY", quantity),
                self._build_leg(short_strike, "PE", "SELL", quantity),
            ]

        if structure_type in {"bull_call_spread_or_bear_put_spread", "reversal_debit_spread", "expiry_directional_scalp"} and len(strikes) == 2:
            buy_strike, sell_strike = strikes
            return [
                self._build_leg(buy_strike, "CE", "BUY", quantity),
                self._build_leg(sell_strike, "CE", "SELL", quantity),
            ]

        if structure_type == "long_straddle_or_strangle":
            if len(strikes) == 1:
                return [
                    self._build_leg(strikes[0], "CE", "BUY", quantity),
                    self._build_leg(strikes[0], "PE", "BUY", quantity),
                ]
            return [
                self._build_leg(strikes[0], "PE", "BUY", quantity),
                self._build_leg(strikes[-1], "CE", "BUY", quantity),
            ]

        return []

    def _build_leg(self, strike: float, option_type: str, side: str, quantity: int) -> dict[str, Any]:
        return {
            "symbol": self._format_leg_symbol(strike, option_type),
            "strike": float(strike),
            "option_type": option_type,
            "side": side,
            "quantity": quantity,
        }

    def _infer_trade_bias(self, playbook: str, structure_type: str, legs: list[dict[str, Any]]) -> str:
        if structure_type == "iron_condor":
            return "NEUTRAL"
        option_types = {str(leg.get("option_type", "")).upper() for leg in legs if leg.get("option_type")}
        if option_types == {"CE"}:
            return "BULLISH"
        if option_types == {"PE"}:
            return "BEARISH"
        if playbook == "iron_condor":
            return "NEUTRAL"
        return "DEFINED_RISK"

    @staticmethod
    def _format_leg_symbol(strike: float, option_type: str) -> str:
        strike_text = int(strike) if float(strike).is_integer() else strike
        return f"NIFTY {strike_text} {option_type}".strip()

    @staticmethod
    def _compute_holding_minutes(opened_at: str, closed_at: str) -> float | None:
        if not opened_at or not closed_at:
            return None
        try:
            opened_dt = datetime.fromisoformat(opened_at)
            closed_dt = datetime.fromisoformat(closed_at)
        except ValueError:
            return None
        return round(max((closed_dt - opened_dt).total_seconds(), 0.0) / 60.0, 2)

    @staticmethod
    def _safe_int(value: Any, *, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_float_or_none(value: Any) -> float | None:
        if value in {None, ""}:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _stringify_value(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (dict, list, tuple)):
            return json.dumps(value, sort_keys=True, ensure_ascii=False)
        return str(value)

    @staticmethod
    def _parse_json_value(value: Any, *, default: Any) -> Any:
        if isinstance(value, type(default)):
            return value
        if value in {None, ""}:
            return default
        try:
            return json.loads(value)
        except Exception:
            return default

    @staticmethod
    def _stringify_json(value: Any, *, default: Any) -> str:
        parsed = TradeRecorder._parse_json_value(value, default=default)
        return json.dumps(parsed, sort_keys=True, ensure_ascii=False)

    @staticmethod
    def _infer_opened_at(trade_id: str) -> str:
        parts = str(trade_id or "").split("-")
        if len(parts) < 3:
            return ""
        date_part, time_part = parts[1], parts[2]
        if len(date_part) != 8 or len(time_part) != 4 or not date_part.isdigit() or not time_part.isdigit():
            return ""
        try:
            opened_dt = datetime.strptime(f"{date_part}{time_part}", "%Y%m%d%H%M").replace(tzinfo=IST)
        except ValueError:
            return ""
        return opened_dt.isoformat()


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
