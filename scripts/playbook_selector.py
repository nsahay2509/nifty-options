"""State-to-playbook selection for the rebuilt NIFTY runtime."""

from __future__ import annotations

from dataclasses import dataclass

from scripts.log import get_logger
from scripts.schema import PlaybookDecision, StateAssessment


logger = get_logger("playbook_selector")


@dataclass(frozen=True)
class PlaybookTemplate:
    """Defines the preferred playbook and fallback alternatives for a state."""

    preferred: str
    alternatives: tuple[str, ...] = ()
    banned: tuple[str, ...] = ()


PLAYBOOK_MAP: dict[str, PlaybookTemplate] = {
    "Gap Continuation": PlaybookTemplate(
        preferred="bull_call_spread_or_bear_put_spread",
        alternatives=("long_call_or_long_put", "tactical_continuation_scalp"),
        banned=("iron_condor", "iron_fly", "passive_short_premium"),
    ),
    "Gap Mean Reversion": PlaybookTemplate(
        preferred="reversal_debit_spread",
        alternatives=("long_call_or_long_put", "reversal_scalp"),
        banned=("passive_short_premium",),
    ),
    "Trend Continuation": PlaybookTemplate(
        preferred="bull_call_spread_or_bear_put_spread",
        alternatives=("long_call_or_long_put", "trend_scalp"),
        banned=("iron_condor", "fade_trade"),
    ),
    "Controlled Range": PlaybookTemplate(
        preferred="call_or_put_credit_spread",
        alternatives=("iron_condor", "small_mean_reversion_scalp"),
        banned=("aggressive_long_option", "trend_following_playbook"),
    ),
    "Volatility Expansion": PlaybookTemplate(
        preferred="long_straddle_or_strangle",
        alternatives=("delayed_directional_debit_spread",),
        banned=("iron_condor", "passive_credit_spread"),
    ),
    "Expiry Compression": PlaybookTemplate(
        preferred="iron_condor",
        alternatives=("iron_fly", "defined_risk_credit_spread"),
        banned=("naked_short_premium", "late_long_option_chase"),
    ),
    "Expiry Gamma Expansion": PlaybookTemplate(
        preferred="expiry_directional_scalp",
        alternatives=("small_directional_spread", "selective_long_option"),
        banned=("passive_premium_selling", "slow_swing_hold"),
    ),
    "Choppy Transition": PlaybookTemplate(
        preferred="no_trade",
        alternatives=("wait",),
        banned=("trend_following_playbook", "range_selling_playbook"),
    ),
}


class PlaybookSelector:
    """Selects a concrete playbook family from the current state and edge decision."""

    def __init__(self) -> None:
        self.logger = logger

    def select(self, assessment: StateAssessment, edge_decision: PlaybookDecision) -> PlaybookDecision:
        """Return the preferred playbook for the current market state."""
        if edge_decision.no_trade:
            return self._decision(
                playbook_name="no_trade",
                reason=edge_decision.reason,
                no_trade=True,
                alternatives=edge_decision.alternatives,
            )

        template = PLAYBOOK_MAP.get(assessment.state_name)
        if template is None:
            return self._decision(
                playbook_name=edge_decision.playbook_name or "no_trade",
                reason=f"fallback_from_edge_filter:{edge_decision.reason}",
                no_trade=edge_decision.no_trade,
                alternatives=edge_decision.alternatives,
            )

        return self._decision(
            playbook_name=template.preferred,
            reason=f"state_playbook_fit:{assessment.state_name}",
            no_trade=False,
            alternatives=template.alternatives,
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
            "PLAYBOOK | selected=%s no_trade=%s reason=%s alternatives=%s",
            decision.playbook_name,
            decision.no_trade,
            decision.reason,
            ",".join(decision.alternatives),
        )
        return decision


def select_playbook(assessment: StateAssessment, edge_decision: PlaybookDecision) -> PlaybookDecision:
    """Convenience wrapper for one-shot playbook selection."""
    return PlaybookSelector().select(assessment, edge_decision)
