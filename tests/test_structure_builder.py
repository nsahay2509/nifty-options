from __future__ import annotations

from scripts.schema import StructureProposal
from scripts.structure_builder import StructureBuilder


def test_builder_creates_directional_debit_spread_structure() -> None:
    proposal = StructureBuilder().build(
        playbook_name="bull_call_spread_or_bear_put_spread",
        underlying_price=22540,
        days_to_expiry=2,
    )

    assert proposal.structure_type == "bull_call_spread_or_bear_put_spread"
    assert proposal.expiry == "same_week"
    assert proposal.strikes == (22550.0, 22650.0)


def test_builder_creates_iron_condor_for_range_playbook() -> None:
    proposal = StructureBuilder().build(
        playbook_name="iron_condor",
        underlying_price=22540,
        days_to_expiry=0,
    )

    assert proposal.structure_type == "iron_condor"
    assert proposal.expiry == "same_day"
    assert proposal.strikes == (22350.0, 22450.0, 22650.0, 22750.0)


def test_builder_creates_long_volatility_structure() -> None:
    proposal = StructureBuilder().build(
        playbook_name="long_straddle_or_strangle",
        underlying_price=22540,
        days_to_expiry=3,
    )

    assert proposal.structure_type == "long_straddle_or_strangle"
    assert proposal.expiry == "same_week"
    assert proposal.strikes == (22550.0,)


def test_builder_returns_no_trade_structure_when_requested() -> None:
    proposal = StructureBuilder().build(
        playbook_name="no_trade",
        underlying_price=22540,
        days_to_expiry=4,
    )

    assert proposal == StructureProposal(structure_type="no_trade", notes="No trade selected")
