"""Market-state classification for the rebuilt NIFTY runtime."""

from __future__ import annotations

from dataclasses import dataclass

from scripts.log import get_logger
from scripts.schema import SessionSnapshot, StateAssessment


logger = get_logger("state_engine")


@dataclass(frozen=True)
class StateThresholds:
    """Heuristic thresholds for the first working state engine."""

    gap_threshold_pct: float = 0.003
    controlled_range_max_pct: float = 0.0035
    midpoint_tolerance_pct: float = 0.0015
    trend_extension_pct: float = 0.0025
    volatility_expansion_pct: float = 0.009
    expiry_gamma_expansion_pct: float = 0.01
    close_near_extreme_min: float = 0.75
    close_near_extreme_max: float = 0.25


class StateEngine:
    """Converts a `SessionSnapshot` into a practical first-pass market state."""

    def __init__(self, *, thresholds: StateThresholds | None = None) -> None:
        self.thresholds = thresholds or StateThresholds()
        self.logger = logger

    def assess(self, snapshot: SessionSnapshot) -> StateAssessment:
        """Classify the current session snapshot into one working state."""
        if snapshot.index_candle is None or snapshot.session_references is None:
            return self._build_assessment(
                "Choppy Transition",
                confidence="low",
                ambiguity="insufficient_session_data",
                tradeable=False,
                evidence={"reason": "missing_index_or_session_references"},
            )

        candle = snapshot.index_candle
        refs = snapshot.session_references
        prior_levels = snapshot.prior_day_levels

        prior_close = prior_levels.close if prior_levels is not None else candle.close
        denominator = max(abs(prior_close), 1.0)
        session_open = float(snapshot.raw_context.get("session_open", candle.open))
        current_price = candle.close
        close_location = self._close_location(current_price, refs.intraday_high, refs.intraday_low)
        close_near_extreme = (
            close_location >= self.thresholds.close_near_extreme_min
            or close_location <= self.thresholds.close_near_extreme_max
        )
        range_pct = refs.realized_range / denominator
        distance_to_mid_pct = abs(current_price - refs.session_midpoint) / denominator
        session_extension_pct = abs(current_price - session_open) / denominator
        gap_pct = (session_open - prior_close) / denominator

        evidence = {
            "current_price": current_price,
            "prior_close": prior_close,
            "session_open": session_open,
            "gap_pct": round(gap_pct, 6),
            "realized_range": refs.realized_range,
            "realized_range_pct": round(range_pct, 6),
            "distance_to_mid_pct": round(distance_to_mid_pct, 6),
            "close_location": round(close_location, 4),
            "days_to_expiry": snapshot.days_to_expiry,
            "session_phase": snapshot.session_phase,
        }

        expiry_state = self._classify_expiry_state(snapshot, range_pct, distance_to_mid_pct, close_near_extreme, evidence)
        if expiry_state is not None:
            return expiry_state

        gap_state = self._classify_gap_state(snapshot, gap_pct, session_open, prior_close, evidence)
        if gap_state is not None:
            return gap_state

        if close_near_extreme and session_extension_pct >= self.thresholds.trend_extension_pct:
            return self._build_assessment(
                "Trend Continuation",
                confidence="high" if range_pct >= self.thresholds.controlled_range_max_pct else "medium",
                ambiguity="",
                tradeable=True,
                evidence=evidence,
            )

        if (
            range_pct <= self.thresholds.controlled_range_max_pct
            and distance_to_mid_pct <= self.thresholds.midpoint_tolerance_pct
        ):
            return self._build_assessment(
                "Controlled Range",
                confidence="high",
                ambiguity="",
                tradeable=True,
                evidence=evidence,
            )

        if range_pct >= self.thresholds.volatility_expansion_pct:
            return self._build_assessment(
                "Volatility Expansion",
                confidence="medium",
                ambiguity="direction_unstable" if not close_near_extreme else "",
                tradeable=close_near_extreme,
                evidence=evidence,
            )

        return self._build_assessment(
            "Choppy Transition",
            confidence="medium",
            ambiguity="mixed_structure",
            tradeable=False,
            evidence=evidence,
        )

    def _classify_expiry_state(
        self,
        snapshot: SessionSnapshot,
        range_pct: float,
        distance_to_mid_pct: float,
        close_near_extreme: bool,
        evidence: dict,
    ) -> StateAssessment | None:
        dte = snapshot.days_to_expiry
        if dte is None or dte > 1:
            return None

        if range_pct >= self.thresholds.expiry_gamma_expansion_pct:
            return self._build_assessment(
                "Expiry Gamma Expansion",
                confidence="high" if close_near_extreme else "medium",
                ambiguity="" if close_near_extreme else "expiry_direction_unstable",
                tradeable=True,
                evidence=evidence,
            )

        if (
            range_pct <= self.thresholds.controlled_range_max_pct
            and distance_to_mid_pct <= self.thresholds.midpoint_tolerance_pct
        ):
            return self._build_assessment(
                "Expiry Compression",
                confidence="high",
                ambiguity="",
                tradeable=True,
                evidence=evidence,
            )

        return None

    def _classify_gap_state(
        self,
        snapshot: SessionSnapshot,
        gap_pct: float,
        session_open: float,
        prior_close: float,
        evidence: dict,
    ) -> StateAssessment | None:
        if abs(gap_pct) < self.thresholds.gap_threshold_pct:
            return None

        if snapshot.index_candle is None or snapshot.session_references is None:
            return None

        if snapshot.session_phase not in {"opening_range", "early_session", "mid_session"}:
            return None

        current_price = snapshot.index_candle.close
        refs = snapshot.session_references
        moved_toward_gap_direction = abs(current_price - prior_close) > abs(session_open - prior_close)

        bullish_acceptance = (
            gap_pct > 0
            and current_price > refs.opening_range_high
            and moved_toward_gap_direction
        )
        bearish_acceptance = (
            gap_pct < 0
            and current_price < refs.opening_range_low
            and moved_toward_gap_direction
        )
        bullish_reversion = gap_pct > 0 and current_price < session_open and current_price < refs.session_midpoint
        bearish_reversion = gap_pct < 0 and current_price > session_open and current_price > refs.session_midpoint

        if bullish_acceptance or bearish_acceptance:
            return self._build_assessment(
                "Gap Continuation",
                confidence="high",
                ambiguity="",
                tradeable=True,
                evidence=evidence,
            )

        if bullish_reversion or bearish_reversion:
            return self._build_assessment(
                "Gap Mean Reversion",
                confidence="medium",
                ambiguity="gap_failure_still_developing",
                tradeable=True,
                evidence=evidence,
            )

        return None

    def _build_assessment(
        self,
        state_name: str,
        *,
        confidence: str,
        ambiguity: str,
        tradeable: bool,
        evidence: dict,
    ) -> StateAssessment:
        assessment = StateAssessment(
            state_name=state_name,
            confidence=confidence,
            ambiguity=ambiguity,
            tradeable=tradeable,
            evidence=evidence,
        )
        self.logger.info(
            "STATE | state=%s confidence=%s tradeable=%s ambiguity=%s evidence=%s",
            assessment.state_name,
            assessment.confidence,
            assessment.tradeable,
            assessment.ambiguity or "none",
            assessment.evidence,
        )
        return assessment

    @staticmethod
    def _close_location(price: float, session_high: float, session_low: float) -> float:
        if session_high <= session_low:
            return 0.5
        return (price - session_low) / (session_high - session_low)


def assess_state(snapshot: SessionSnapshot) -> StateAssessment:
    """Convenience wrapper for one-shot market-state assessment."""
    return StateEngine().assess(snapshot)
