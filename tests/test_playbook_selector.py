from __future__ import annotations

from scripts.playbook_selector import PlaybookSelector
from scripts.schema import PlaybookDecision, StateAssessment


def test_selector_prefers_directional_spread_for_gap_continuation() -> None:
    assessment = StateAssessment(state_name="Gap Continuation", confidence="high", tradeable=True)
    edge_decision = PlaybookDecision(
        playbook_name="directional_debit_spread",
        reason="directional_edge_confirmed",
        no_trade=False,
        alternatives=("long_option", "tactical_scalp"),
    )

    selected = PlaybookSelector().select(assessment, edge_decision)

    assert selected.playbook_name == "bull_call_spread_or_bear_put_spread"
    assert selected.no_trade is False


def test_selector_returns_no_trade_when_edge_filter_blocks_trade() -> None:
    assessment = StateAssessment(state_name="Choppy Transition", confidence="medium", tradeable=False)
    edge_decision = PlaybookDecision(
        playbook_name="no_trade",
        reason="state_marked_untradeable",
        no_trade=True,
        alternatives=("wait",),
    )

    selected = PlaybookSelector().select(assessment, edge_decision)

    assert selected.playbook_name == "no_trade"
    assert selected.no_trade is True


def test_selector_maps_expiry_compression_to_iron_condor_family() -> None:
    assessment = StateAssessment(state_name="Expiry Compression", confidence="high", tradeable=True)
    edge_decision = PlaybookDecision(
        playbook_name="defined_risk_credit_spread",
        reason="expiry_decay_edge_confirmed",
        no_trade=False,
        alternatives=("iron_condor", "iron_fly"),
    )

    selected = PlaybookSelector().select(assessment, edge_decision)

    assert selected.playbook_name == "iron_condor"
    assert "iron_fly" in selected.alternatives


def test_selector_maps_expiry_gamma_expansion_to_tactical_directional_playbook() -> None:
    assessment = StateAssessment(state_name="Expiry Gamma Expansion", confidence="high", tradeable=True)
    edge_decision = PlaybookDecision(
        playbook_name="tactical_directional_scalp",
        reason="expiry_gamma_movement_edge",
        no_trade=False,
        alternatives=("small_directional_spread",),
    )

    selected = PlaybookSelector().select(assessment, edge_decision)

    assert selected.playbook_name == "expiry_directional_scalp"
    assert selected.no_trade is False
