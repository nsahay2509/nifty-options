"""Edge validation and no-trade filtering for the rebuilt NIFTY runtime."""

from __future__ import annotations

from dataclasses import dataclass

from scripts.log import get_logger
from scripts.schema import PlaybookDecision, StateAssessment


logger = get_logger("edge_filter")


@dataclass(frozen=True)
class EdgeThresholds:
    """Minimum clarity rules before a state becomes actionable."""

    min_confidence_rank: int = 2
    max_acceptable_range_pct_for_decay: float = 0.0045
    min_range_pct_for_long_vol: float = 0.008


CONFIDENCE_RANK = {
    "low": 1,
    "medium": 2,
    "high": 3,
}


class EdgeFilter:
    """Converts a classified state into action or explicit `no_trade`."""

    def __init__(self, *, thresholds: EdgeThresholds | None = None) -> None:
        self.thresholds = thresholds or EdgeThresholds()
        self.logger = logger

    def evaluate(self, assessment: StateAssessment) -> PlaybookDecision:
        """Decide whether the current state offers actionable edge."""
        confidence_rank = CONFIDENCE_RANK.get(assessment.confidence, 0)
        realized_range_pct = float(assessment.evidence.get("realized_range_pct", 0.0))

        if not assessment.tradeable:
            return self._decision(
                playbook_name="no_trade",
                reason="state_marked_untradeable",
                no_trade=True,
                alternatives=("wait",),
            )

        if confidence_rank < self.thresholds.min_confidence_rank:
            return self._decision(
                playbook_name="no_trade",
                reason="state_not_clear_enough",
                no_trade=True,
                alternatives=("wait",),
            )

        if assessment.state_name in {"Gap Continuation", "Trend Continuation", "Gap Mean Reversion"}:
            return self._decision(
                playbook_name="directional_debit_spread",
                reason="directional_edge_confirmed",
                no_trade=False,
                alternatives=("long_option", "tactical_scalp"),
            )

        if assessment.state_name == "Controlled Range":
            return self._decision(
                playbook_name="defined_risk_credit_spread",
                reason="contained_market_structure",
                no_trade=False,
                alternatives=("iron_condor", "small_mean_reversion_scalp"),
            )

        if assessment.state_name == "Volatility Expansion":
            if realized_range_pct < self.thresholds.min_range_pct_for_long_vol:
                return self._decision(
                    playbook_name="no_trade",
                    reason="movement_edge_not_large_enough",
                    no_trade=True,
                    alternatives=("wait",),
                )
            return self._decision(
                playbook_name="long_volatility_setup",
                reason="realized_movement_expanding",
                no_trade=False,
                alternatives=("directional_debit_spread",),
            )

        if assessment.state_name == "Expiry Compression":
            if realized_range_pct > self.thresholds.max_acceptable_range_pct_for_decay:
                return self._decision(
                    playbook_name="no_trade",
                    reason="expiry_containment_not_clean_enough",
                    no_trade=True,
                    alternatives=("wait",),
                )
            return self._decision(
                playbook_name="defined_risk_credit_spread",
                reason="expiry_decay_edge_confirmed",
                no_trade=False,
                alternatives=("iron_condor", "iron_fly"),
            )

        if assessment.state_name == "Expiry Gamma Expansion":
            return self._decision(
                playbook_name="tactical_directional_scalp",
                reason="expiry_gamma_movement_edge",
                no_trade=False,
                alternatives=("small_directional_spread",),
            )

        return self._decision(
            playbook_name="no_trade",
            reason="no_clear_edge_for_state",
            no_trade=True,
            alternatives=("wait",),
        )

    def _decision(
        self,
        *,
        playbook_name: str,
        reason: str,
        no_trade: bool,
        alternatives: tuple[str, ...],
    ) -> PlaybookDecision:
        decision = PlaybookDecision(
            playbook_name=playbook_name,
            reason=reason,
            no_trade=no_trade,
            alternatives=alternatives,
        )
        self.logger.info(
            "EDGE | playbook=%s no_trade=%s reason=%s alternatives=%s",
            decision.playbook_name,
            decision.no_trade,
            decision.reason,
            ",".join(decision.alternatives),
        )
        return decision


def evaluate_edge(assessment: StateAssessment) -> PlaybookDecision:
    """Convenience wrapper for one-shot edge evaluation."""
    return EdgeFilter().evaluate(assessment)
