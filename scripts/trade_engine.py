"""Thin orchestration layer for runtime trade decisions."""

from __future__ import annotations

from dataclasses import dataclass

from scripts.edge_filter import EdgeFilter
from scripts.log import get_logger
from scripts.playbook_selector import PlaybookSelector
from scripts.schema import PlaybookDecision, SessionSnapshot, StateAssessment, StructureProposal
from scripts.state_engine import StateEngine
from scripts.structure_builder import StructureBuilder


logger = get_logger("trade_engine")


@dataclass(frozen=True)
class TradeEvaluation:
    """Represents the full decision chain for one trade evaluation."""

    state_assessment: StateAssessment
    edge_decision: PlaybookDecision
    playbook_decision: PlaybookDecision
    structure_proposal: StructureProposal


class TradeEngine:
    """Coordinates the first working end-to-end decision pipeline."""

    def __init__(
        self,
        *,
        state_engine: StateEngine | None = None,
        edge_filter: EdgeFilter | None = None,
        playbook_selector: PlaybookSelector | None = None,
        structure_builder: StructureBuilder | None = None,
    ) -> None:
        self.state_engine = state_engine or StateEngine()
        self.edge_filter = edge_filter or EdgeFilter()
        self.playbook_selector = playbook_selector or PlaybookSelector()
        self.structure_builder = structure_builder or StructureBuilder()
        self.logger = logger

    def evaluate(self, snapshot: SessionSnapshot) -> TradeEvaluation:
        """Run the full decision path from state to proposed structure."""
        state_assessment = self.state_engine.assess(snapshot)
        edge_decision = self.edge_filter.evaluate(state_assessment)
        playbook_decision = self.playbook_selector.select(state_assessment, edge_decision)

        underlying_price = snapshot.index_candle.close if snapshot.index_candle is not None else 0.0
        structure_proposal = self.structure_builder.build(
            playbook_name=playbook_decision.playbook_name,
            underlying_price=underlying_price,
            days_to_expiry=snapshot.days_to_expiry,
        )

        result = TradeEvaluation(
            state_assessment=state_assessment,
            edge_decision=edge_decision,
            playbook_decision=playbook_decision,
            structure_proposal=structure_proposal,
        )
        self.logger.info(
            "TRADE_EVAL | state=%s edge=%s playbook=%s structure=%s no_trade=%s",
            result.state_assessment.state_name,
            result.edge_decision.reason,
            result.playbook_decision.playbook_name,
            result.structure_proposal.structure_type,
            result.playbook_decision.no_trade,
        )
        return result


def evaluate_trade(snapshot: SessionSnapshot) -> TradeEvaluation:
    """Convenience wrapper for one-shot trade evaluation."""
    return TradeEngine().evaluate(snapshot)
