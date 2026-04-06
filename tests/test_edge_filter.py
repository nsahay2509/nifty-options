from __future__ import annotations

from scripts.edge_filter import EdgeFilter
from scripts.schema import StateAssessment


def test_edge_filter_allows_gap_continuation_directional_edge() -> None:
    assessment = StateAssessment(
        state_name="Gap Continuation",
        confidence="high",
        ambiguity="",
        tradeable=True,
        evidence={"realized_range_pct": 0.006, "days_to_expiry": 2},
    )

    decision = EdgeFilter().evaluate(assessment)

    assert decision.no_trade is False
    assert decision.playbook_name == "directional_debit_spread"


def test_edge_filter_prefers_no_trade_for_choppy_transition() -> None:
    assessment = StateAssessment(
        state_name="Choppy Transition",
        confidence="medium",
        ambiguity="mixed_structure",
        tradeable=False,
        evidence={"realized_range_pct": 0.005},
    )

    decision = EdgeFilter().evaluate(assessment)

    assert decision.no_trade is True
    assert decision.playbook_name == "no_trade"


def test_edge_filter_maps_expiry_compression_to_defined_risk_premium_selling() -> None:
    assessment = StateAssessment(
        state_name="Expiry Compression",
        confidence="high",
        ambiguity="",
        tradeable=True,
        evidence={"realized_range_pct": 0.002, "days_to_expiry": 0},
    )

    decision = EdgeFilter().evaluate(assessment)

    assert decision.no_trade is False
    assert decision.playbook_name == "defined_risk_credit_spread"


def test_edge_filter_blocks_low_confidence_tradeable_state() -> None:
    assessment = StateAssessment(
        state_name="Volatility Expansion",
        confidence="low",
        ambiguity="direction_unstable",
        tradeable=True,
        evidence={"realized_range_pct": 0.012},
    )

    decision = EdgeFilter().evaluate(assessment)

    assert decision.no_trade is True
    assert decision.reason == "state_not_clear_enough"
