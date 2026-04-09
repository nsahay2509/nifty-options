"""Live paper MTM tracking for the rebuilt NIFTY runtime."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Callable

from scripts.config import DATA_DIR
from scripts.log import get_logger
from scripts.option_resolver import resolve_nifty_option
from scripts.schema import MarketInstrument, MarketTick, StructureProposal


logger = get_logger("paper_mtm")

InstrumentLookup = Callable[..., MarketInstrument]
TradeCloseHandler = Callable[[dict[str, object]], None]


@dataclass
class PaperLeg:
    instrument: MarketInstrument
    side: str
    quantity: int = 1
    entry_price: float | None = None
    last_price: float | None = None

    @property
    def sign(self) -> int:
        return 1 if self.side.upper() == "BUY" else -1

    @property
    def multiplier(self) -> int:
        lot_size = self.instrument.lot_size if self.instrument.lot_size > 0 else 1
        qty = self.quantity if self.quantity > 0 else 1
        return lot_size * qty

    def signed_entry_value(self) -> float:
        return self.sign * float(self.entry_price or 0.0)

    def signed_current_value(self) -> float:
        return self.sign * float(self.last_price or 0.0)

    def signed_points(self) -> float:
        if self.entry_price is None or self.last_price is None:
            return 0.0
        return self.sign * (float(self.last_price) - float(self.entry_price))

    def to_dict(self) -> dict[str, object]:
        return {
            "security_id": self.instrument.security_id,
            "symbol": self.instrument.name,
            "strike": self.instrument.strike,
            "option_type": self.instrument.option_type,
            "side": self.side,
            "quantity": self.quantity,
            "lot_size": self.instrument.lot_size,
            "entry_price": self.entry_price,
            "last_price": self.last_price,
        }


class PaperMtmTracker:
    """Tracks one active paper structure and marks it to live option prices."""

    def __init__(
        self,
        *,
        output_file: Path | None = None,
        instrument_lookup: InstrumentLookup | None = None,
        session_date: str | None = None,
        on_trade_closed: TradeCloseHandler | None = None,
    ) -> None:
        self.output_file = output_file or (DATA_DIR / "reports" / "live_paper_mtm.json")
        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        self.instrument_lookup = instrument_lookup or resolve_nifty_option
        self.logger = logger
        self._session_date = session_date or date.today().isoformat()
        self._on_trade_closed = on_trade_closed
        self._latest_prices: dict[str, float] = {}
        self._active: dict[str, object] | None = None
        self._realised_pnl_today = 0.0
        self._closed_trade_count = 0
        self._recent_closed: list[dict[str, object]] = []
        self._flat_reason = "No active paper position yet."
        self._last_update_iso = datetime.now(UTC).isoformat()
        self._restore_summary_state()
        self._write_snapshot(self.snapshot())

    def _reset_for_session(self, session_date: str, *, reason: str = "No active paper position yet.") -> None:
        self._session_date = session_date or self._session_date
        self._active = None
        self._recent_closed = []
        self._realised_pnl_today = 0.0
        self._closed_trade_count = 0
        self._flat_reason = reason

    def activate_position(
        self,
        *,
        trade_id: str,
        session_date: str,
        playbook: str,
        structure: StructureProposal,
        underlying_price: float,
        quantity: int = 1,
        as_of: date | None = None,
    ) -> dict[str, object]:
        as_of_date = as_of or date.today()
        if session_date and session_date != self._session_date:
            self.logger.info(
                "PAPER_MTM_SESSION_ROLLOVER | previous_session=%s current_session=%s",
                self._session_date,
                session_date,
            )
            self._reset_for_session(session_date)

        signature = (playbook, structure.structure_type, structure.expiry, tuple(structure.strikes))

        if self._active and self._active.get("signature") == signature:
            self._active["last_signal_id"] = trade_id
            self._active["underlying_price"] = underlying_price
            self._recompute_snapshot()
            return self.snapshot()

        if self._active:
            self.close_active_position(reason="structure_change")

        legs = self._build_legs(structure=structure, quantity=quantity, as_of=as_of_date)
        self._active = {
            "signature": signature,
            "trade_id": trade_id,
            "last_signal_id": trade_id,
            "session_date": session_date,
            "playbook": playbook,
            "structure_type": structure.structure_type,
            "expiry": structure.expiry,
            "strikes": list(structure.strikes),
            "underlying_price": underlying_price,
            "estimated_premium": structure.estimated_premium,
            "entry_credit": 0.0,
            "entry_debit": 0.0,
            "current_close_value": 0.0,
            "mtm_points": 0.0,
            "unrealised_pnl": 0.0,
            "live": False,
            "mode": "awaiting_option_ticks",
            "reason": "Waiting for option ticks for all active legs.",
            "last_update": self._last_update_iso,
            "legs": legs,
        }

        for leg in legs:
            known = self._latest_prices.get(leg.instrument.security_id)
            if known is not None:
                leg.entry_price = known
                leg.last_price = known

        self.logger.info(
            "PAPER_MTM_ACTIVATE | trade_id=%s playbook=%s structure=%s strikes=%s",
            trade_id,
            playbook,
            structure.structure_type,
            structure.strikes,
        )
        self._recompute_snapshot()
        return self.snapshot()

    def close_active_position(self, *, reason: str, closed_at: datetime | None = None) -> dict[str, object]:
        """Book the current open paper MTM into realised P&L and flatten the tracker."""
        if not self._active:
            return self.snapshot()

        closed_ts = (closed_at or datetime.now(UTC)).isoformat()
        realised = round(float(self._active.get("unrealised_pnl", 0.0) or 0.0), 2)
        closed_trade = {
            "trade_id": str(self._active.get("trade_id", "")),
            "session_date": str(self._active.get("session_date", self._session_date)),
            "playbook": str(self._active.get("playbook", "")),
            "structure_type": str(self._active.get("structure_type", "")),
            "exit_reason": reason,
            "closed_at": closed_ts,
            "mtm_points": round(float(self._active.get("mtm_points", 0.0) or 0.0), 2),
            "entry_credit": round(float(self._active.get("entry_credit", 0.0) or 0.0), 2),
            "entry_debit": round(float(self._active.get("entry_debit", 0.0) or 0.0), 2),
            "current_close_value": round(float(self._active.get("current_close_value", 0.0) or 0.0), 2),
            "underlying_price": float(self._active.get("underlying_price", 0.0) or 0.0),
            "legs": [leg.to_dict() for leg in self._active.get("legs", []) if isinstance(leg, PaperLeg)],
            "realised_pnl": realised,
        }
        self._realised_pnl_today += realised
        self._closed_trade_count += 1
        self._recent_closed = [closed_trade, *self._recent_closed][:10]
        self._flat_reason = f"Last paper trade was closed: {reason}."
        self._last_update_iso = closed_ts

        self.logger.info(
            "PAPER_MTM_CLOSE | trade_id=%s reason=%s realised_pnl=%s",
            closed_trade["trade_id"],
            reason,
            realised,
        )
        self._active = None
        self._write_snapshot(self.snapshot())
        if self._on_trade_closed is not None:
            try:
                self._on_trade_closed(dict(closed_trade))
            except Exception as exc:
                self.logger.warning("PAPER_MTM_CLOSE_CALLBACK_FAILED | trade_id=%s reason=%s", closed_trade["trade_id"], exc)
        return self.snapshot()

    def preserve_active_position(self, *, reason: str) -> dict[str, object]:
        """Persist the current in-session paper state without forcing a close."""
        if not self._active:
            return self.snapshot()

        self._active["reason"] = reason
        self._write_snapshot(self.snapshot())
        self.logger.info(
            "PAPER_MTM_PRESERVE | trade_id=%s reason=%s",
            self._active.get("trade_id", ""),
            reason,
        )
        return self.snapshot()

    def on_tick(self, tick: MarketTick) -> None:
        mark_price = self._mark_price(tick)
        self._latest_prices[tick.instrument.security_id] = mark_price
        self._last_update_iso = tick.timestamp.isoformat()
        if not self._active:
            return

        touched = False
        if tick.instrument.instrument_type == "INDEX":
            self._active["underlying_price"] = tick.ltp
            touched = True

        option_leg_touched = False
        for leg in self._active.get("legs", []):
            if not isinstance(leg, PaperLeg):
                continue
            if leg.instrument.security_id != tick.instrument.security_id:
                continue
            if leg.entry_price is None:
                leg.entry_price = mark_price
            leg.last_price = mark_price
            touched = True
            option_leg_touched = True

        if touched:
            self._active["last_update"] = tick.timestamp.isoformat()
            if option_leg_touched:
                self._recompute_snapshot()
            else:
                self._write_snapshot(self.snapshot())

    def _mark_price(self, tick: MarketTick) -> float:
        if tick.instrument.instrument_type == "OPTION":
            bid = float(tick.best_bid_price or 0.0)
            ask = float(tick.best_ask_price or 0.0)
            if bid > 0 and ask > 0:
                return (bid + ask) / 2.0
        return float(tick.ltp)

    def snapshot(self) -> dict[str, object]:
        if not self._active:
            return {
                "live": False,
                "mode": "waiting_for_trade",
                "reason": self._flat_reason,
                "trade_id": "",
                "last_signal_id": "",
                "session_date": self._session_date,
                "playbook": "",
                "structure_type": "",
                "expiry": "",
                "strikes": [],
                "entry_credit": 0.0,
                "entry_debit": 0.0,
                "current_close_value": 0.0,
                "mtm_points": 0.0,
                "unrealised_pnl": 0.0,
                "realised_pnl_today": round(self._realised_pnl_today, 2),
                "closed_trade_count": self._closed_trade_count,
                "recent_closed": self._recent_closed,
                "underlying_price": 0.0,
                "last_update": self._last_update_iso,
                "legs": [],
            }

        return {
            "live": bool(self._active.get("live", False)),
            "mode": str(self._active.get("mode", "awaiting_option_ticks")),
            "reason": str(self._active.get("reason", "")),
            "trade_id": str(self._active.get("trade_id", "")),
            "last_signal_id": str(self._active.get("last_signal_id", "")),
            "session_date": str(self._active.get("session_date", "")),
            "playbook": str(self._active.get("playbook", "")),
            "structure_type": str(self._active.get("structure_type", "")),
            "expiry": str(self._active.get("expiry", "")),
            "strikes": list(self._active.get("strikes", [])),
            "entry_credit": round(float(self._active.get("entry_credit", 0.0) or 0.0), 2),
            "entry_debit": round(float(self._active.get("entry_debit", 0.0) or 0.0), 2),
            "current_close_value": round(float(self._active.get("current_close_value", 0.0) or 0.0), 2),
            "mtm_points": round(float(self._active.get("mtm_points", 0.0) or 0.0), 2),
            "unrealised_pnl": round(float(self._active.get("unrealised_pnl", 0.0) or 0.0), 2),
            "realised_pnl_today": round(self._realised_pnl_today, 2),
            "closed_trade_count": self._closed_trade_count,
            "recent_closed": self._recent_closed,
            "underlying_price": float(self._active.get("underlying_price", 0.0) or 0.0),
            "last_update": str(self._active.get("last_update", self._last_update_iso)),
            "legs": [leg.to_dict() for leg in self._active.get("legs", []) if isinstance(leg, PaperLeg)],
        }

    def _build_legs(self, *, structure: StructureProposal, quantity: int, as_of: date) -> list[PaperLeg]:
        strikes = tuple(float(strike) for strike in structure.strikes)
        expiry_hint = structure.expiry or "same_week"

        if structure.structure_type == "iron_condor" and len(strikes) == 4:
            low_wing, low_short, high_short, high_wing = strikes
            return [
                self._make_leg(strike=low_wing, option_type="PE", side="BUY", quantity=quantity, expiry_hint=expiry_hint, as_of=as_of),
                self._make_leg(strike=low_short, option_type="PE", side="SELL", quantity=quantity, expiry_hint=expiry_hint, as_of=as_of),
                self._make_leg(strike=high_short, option_type="CE", side="SELL", quantity=quantity, expiry_hint=expiry_hint, as_of=as_of),
                self._make_leg(strike=high_wing, option_type="CE", side="BUY", quantity=quantity, expiry_hint=expiry_hint, as_of=as_of),
            ]

        if structure.structure_type in {"call_or_put_credit_spread", "defined_risk_credit_spread"} and len(strikes) == 2:
            long_strike, short_strike = strikes
            return [
                self._make_leg(strike=long_strike, option_type="PE", side="BUY", quantity=quantity, expiry_hint=expiry_hint, as_of=as_of),
                self._make_leg(strike=short_strike, option_type="PE", side="SELL", quantity=quantity, expiry_hint=expiry_hint, as_of=as_of),
            ]

        if structure.structure_type in {"bull_call_spread_or_bear_put_spread", "reversal_debit_spread", "expiry_directional_scalp"} and len(strikes) == 2:
            buy_strike, sell_strike = strikes
            return [
                self._make_leg(strike=buy_strike, option_type="CE", side="BUY", quantity=quantity, expiry_hint=expiry_hint, as_of=as_of),
                self._make_leg(strike=sell_strike, option_type="CE", side="SELL", quantity=quantity, expiry_hint=expiry_hint, as_of=as_of),
            ]

        if structure.structure_type == "long_straddle_or_strangle":
            if len(strikes) == 1:
                strike = strikes[0]
                return [
                    self._make_leg(strike=strike, option_type="CE", side="BUY", quantity=quantity, expiry_hint=expiry_hint, as_of=as_of),
                    self._make_leg(strike=strike, option_type="PE", side="BUY", quantity=quantity, expiry_hint=expiry_hint, as_of=as_of),
                ]
            if len(strikes) >= 2:
                put_strike, call_strike = strikes[0], strikes[-1]
                return [
                    self._make_leg(strike=put_strike, option_type="PE", side="BUY", quantity=quantity, expiry_hint=expiry_hint, as_of=as_of),
                    self._make_leg(strike=call_strike, option_type="CE", side="BUY", quantity=quantity, expiry_hint=expiry_hint, as_of=as_of),
                ]

        self.logger.warning("PAPER_MTM_UNSUPPORTED | structure=%s strikes=%s", structure.structure_type, structure.strikes)
        return []

    def _make_leg(
        self,
        *,
        strike: float,
        option_type: str,
        side: str,
        quantity: int,
        expiry_hint: str,
        as_of: date,
    ) -> PaperLeg:
        instrument = self.instrument_lookup(
            strike=float(strike),
            option_type=option_type,
            expiry_hint=expiry_hint,
            as_of=as_of,
        )
        return PaperLeg(instrument=instrument, side=side, quantity=quantity)

    def _recompute_snapshot(self) -> None:
        if not self._active:
            return

        legs = [leg for leg in self._active.get("legs", []) if isinstance(leg, PaperLeg)]
        if not legs:
            self._active["live"] = False
            self._active["mode"] = "unsupported_structure"
            self._active["reason"] = "Live MTM is not wired for this playbook structure yet."
            self._write_snapshot(self.snapshot())
            return

        if not all(leg.entry_price is not None and leg.last_price is not None for leg in legs):
            self._active["live"] = False
            self._active["mode"] = "awaiting_option_ticks"
            self._active["reason"] = "Waiting for live ticks on all required option legs."
            self._write_snapshot(self.snapshot())
            return

        signed_entry = sum(leg.signed_entry_value() for leg in legs)
        signed_current = sum(leg.signed_current_value() for leg in legs)
        mtm_points = sum(leg.signed_points() for leg in legs)
        unrealised_pnl = sum(leg.signed_points() * leg.multiplier for leg in legs)

        self._active["entry_credit"] = max(-signed_entry, 0.0)
        self._active["entry_debit"] = max(signed_entry, 0.0)
        self._active["current_close_value"] = max(-signed_current, 0.0) if signed_entry <= 0 else max(signed_current, 0.0)
        self._active["mtm_points"] = mtm_points
        self._active["unrealised_pnl"] = unrealised_pnl
        self._active["live"] = True
        self._active["mode"] = "live_mtm"
        self._active["reason"] = "Live MTM is being marked from option-leg ticks."

        self._write_snapshot(self.snapshot())
        self.logger.info(
            "PAPER_MTM_MARK | trade_id=%s live=%s points=%s pnl=%s",
            self._active.get("trade_id", ""),
            self._active.get("live", False),
            round(float(self._active.get("mtm_points", 0.0) or 0.0), 2),
            round(float(self._active.get("unrealised_pnl", 0.0) or 0.0), 2),
        )

    def _restore_summary_state(self) -> None:
        if not self.output_file.exists():
            return
        try:
            payload = json.loads(self.output_file.read_text(encoding="utf-8"))
        except Exception:
            return

        payload_session_date = self._extract_payload_session_date(payload)
        self._flat_reason = str(payload.get("reason", self._flat_reason))
        self._last_update_iso = str(payload.get("last_update", self._last_update_iso))

        if payload_session_date and payload_session_date != self._session_date:
            self.logger.info(
                "PAPER_MTM_SESSION_RESET | previous_session=%s current_session=%s",
                payload_session_date,
                self._session_date,
            )
            self._reset_for_session(self._session_date)
            return

        self._realised_pnl_today = float(payload.get("realised_pnl_today", 0.0) or 0.0)
        self._closed_trade_count = int(payload.get("closed_trade_count", 0) or 0)
        self._recent_closed = list(payload.get("recent_closed", []))[:10]
        self._restore_active_state(payload)

    def _restore_active_state(self, payload: dict[str, object]) -> None:
        if not bool(payload.get("live", False)):
            return

        payload_session_date = str(payload.get("session_date", "") or "")
        if payload_session_date != self._session_date:
            return

        legs_payload = payload.get("legs", [])
        if not isinstance(legs_payload, list) or not legs_payload:
            return

        restored_legs: list[PaperLeg] = []
        expiry_hint = str(payload.get("expiry", "") or "same_week")
        as_of = datetime.strptime(self._session_date, "%Y-%m-%d").date()

        for leg_payload in legs_payload:
            if not isinstance(leg_payload, dict):
                return
            try:
                instrument = self.instrument_lookup(
                    strike=float(leg_payload.get("strike", 0.0) or 0.0),
                    option_type=str(leg_payload.get("option_type", "") or ""),
                    expiry_hint=expiry_hint,
                    as_of=as_of,
                )
            except Exception:
                return

            entry_price = leg_payload.get("entry_price")
            last_price = leg_payload.get("last_price")
            restored_leg = PaperLeg(
                instrument=instrument,
                side=str(leg_payload.get("side", "") or ""),
                quantity=int(leg_payload.get("quantity", 1) or 1),
                entry_price=float(entry_price) if entry_price is not None else None,
                last_price=float(last_price) if last_price is not None else None,
            )
            if restored_leg.entry_price is not None:
                self._latest_prices[instrument.security_id] = restored_leg.entry_price
            if restored_leg.last_price is not None:
                self._latest_prices[instrument.security_id] = restored_leg.last_price
            restored_legs.append(restored_leg)

        strikes = [float(leg.instrument.strike) for leg in restored_legs]
        self._active = {
            "signature": (
                str(payload.get("playbook", "") or ""),
                str(payload.get("structure_type", "") or ""),
                expiry_hint,
                tuple(strikes),
            ),
            "trade_id": str(payload.get("trade_id", "") or ""),
            "last_signal_id": str(payload.get("last_signal_id", "") or payload.get("trade_id", "") or ""),
            "session_date": payload_session_date,
            "playbook": str(payload.get("playbook", "") or ""),
            "structure_type": str(payload.get("structure_type", "") or ""),
            "expiry": expiry_hint,
            "strikes": strikes,
            "underlying_price": float(payload.get("underlying_price", 0.0) or 0.0),
            "estimated_premium": 0.0,
            "entry_credit": float(payload.get("entry_credit", 0.0) or 0.0),
            "entry_debit": float(payload.get("entry_debit", 0.0) or 0.0),
            "current_close_value": float(payload.get("current_close_value", 0.0) or 0.0),
            "mtm_points": float(payload.get("mtm_points", 0.0) or 0.0),
            "unrealised_pnl": float(payload.get("unrealised_pnl", 0.0) or 0.0),
            "live": True,
            "mode": str(payload.get("mode", "live_mtm") or "live_mtm"),
            "reason": str(payload.get("reason", "Active paper trade restored after restart.") or "Active paper trade restored after restart."),
            "last_update": str(payload.get("last_update", self._last_update_iso) or self._last_update_iso),
            "legs": restored_legs,
        }
        self.logger.info(
            "PAPER_MTM_RESTORED | trade_id=%s session_date=%s playbook=%s",
            self._active.get("trade_id", ""),
            payload_session_date,
            self._active.get("playbook", ""),
        )

    def _extract_payload_session_date(self, payload: dict[str, object]) -> str:
        session_date = str(payload.get("session_date", "") or "")
        if session_date:
            return session_date

        recent_closed = payload.get("recent_closed", [])
        if isinstance(recent_closed, list):
            for item in recent_closed:
                if not isinstance(item, dict):
                    continue
                closed_at = str(item.get("closed_at", "") or "")
                if len(closed_at) >= 10:
                    return closed_at[:10]

        last_update = str(payload.get("last_update", "") or "")
        if len(last_update) >= 10:
            return last_update[:10]
        return ""

    def _write_snapshot(self, payload: dict[str, object]) -> None:
        with self.output_file.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
