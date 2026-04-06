"""Trade-structure construction for the rebuilt NIFTY runtime."""

from __future__ import annotations

from dataclasses import dataclass

from scripts.log import get_logger
from scripts.schema import StructureProposal


logger = get_logger("structure_builder")


@dataclass(frozen=True)
class StructureRules:
    """Simple first-pass strike spacing rules for NIFTY structures."""

    strike_step: int = 50
    directional_spread_width: int = 100
    condor_wing_width: int = 100
    condor_body_offset: int = 100
    scalp_spread_width: int = 50


class StructureBuilder:
    """Builds a concrete structure proposal from the selected playbook family."""

    def __init__(self, *, rules: StructureRules | None = None) -> None:
        self.rules = rules or StructureRules()
        self.logger = logger

    def build(
        self,
        *,
        playbook_name: str,
        underlying_price: float,
        days_to_expiry: int | None,
    ) -> StructureProposal:
        """Return the first working structure proposal for a playbook."""
        if playbook_name == "no_trade":
            return StructureProposal(structure_type="no_trade", notes="No trade selected")

        atm = self._round_to_strike(underlying_price)
        expiry = self._expiry_posture(days_to_expiry)

        if playbook_name in {"bull_call_spread_or_bear_put_spread", "reversal_debit_spread"}:
            strikes = (atm, atm + self.rules.directional_spread_width)
            return self._proposal(
                structure_type=playbook_name,
                expiry=expiry,
                strikes=strikes,
                estimated_premium=120.0,
                notes="ATM-to-OTM defined-risk directional spread",
            )

        if playbook_name in {"call_or_put_credit_spread", "defined_risk_credit_spread"}:
            strikes = (atm - self.rules.directional_spread_width, atm)
            return self._proposal(
                structure_type=playbook_name,
                expiry=expiry,
                strikes=strikes,
                estimated_premium=65.0,
                notes="Defined-risk credit spread outside the core value area",
            )

        if playbook_name == "iron_condor":
            strikes = (
                atm - (self.rules.condor_body_offset + self.rules.condor_wing_width),
                atm - self.rules.condor_body_offset,
                atm + self.rules.condor_body_offset,
                atm + (self.rules.condor_body_offset + self.rules.condor_wing_width),
            )
            return self._proposal(
                structure_type="iron_condor",
                expiry=expiry,
                strikes=strikes,
                estimated_premium=95.0,
                notes="Defined-risk range structure around the expected containment zone",
            )

        if playbook_name == "long_straddle_or_strangle":
            return self._proposal(
                structure_type="long_straddle_or_strangle",
                expiry=expiry,
                strikes=(atm,),
                estimated_premium=180.0,
                notes="ATM long-volatility structure for expanding movement",
            )

        if playbook_name == "expiry_directional_scalp":
            strikes = (atm, atm + self.rules.scalp_spread_width)
            return self._proposal(
                structure_type="expiry_directional_scalp",
                expiry=expiry,
                strikes=strikes,
                estimated_premium=70.0,
                notes="Fast-response expiry directional structure with tight risk",
            )

        return self._proposal(
            structure_type=playbook_name,
            expiry=expiry,
            strikes=(atm,),
            estimated_premium=100.0,
            notes="Fallback single-leg placeholder structure",
        )

    def _proposal(
        self,
        *,
        structure_type: str,
        expiry: str,
        strikes: tuple[float, ...],
        estimated_premium: float,
        notes: str,
    ) -> StructureProposal:
        proposal = StructureProposal(
            structure_type=structure_type,
            expiry=expiry,
            strikes=strikes,
            estimated_premium=estimated_premium,
            notes=notes,
        )
        self.logger.info(
            "STRUCTURE | type=%s expiry=%s strikes=%s estimated_premium=%s",
            proposal.structure_type,
            proposal.expiry,
            proposal.strikes,
            proposal.estimated_premium,
        )
        return proposal

    def _round_to_strike(self, price: float) -> float:
        step = self.rules.strike_step
        return float(round(price / step) * step)

    @staticmethod
    def _expiry_posture(days_to_expiry: int | None) -> str:
        if days_to_expiry is None:
            return "same_week"
        if days_to_expiry <= 0:
            return "same_day"
        if days_to_expiry <= 3:
            return "same_week"
        return "next_week"


def build_structure(
    *,
    playbook_name: str,
    underlying_price: float,
    days_to_expiry: int | None,
) -> StructureProposal:
    """Convenience wrapper for one-shot structure construction."""
    return StructureBuilder().build(
        playbook_name=playbook_name,
        underlying_price=underlying_price,
        days_to_expiry=days_to_expiry,
    )
