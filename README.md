# NIFTY Rebuild

This repository is now being rebuilt from first principles.

The design anchor is [STRATEGY_BLUEPRINT.md](/home/ubuntu/nifty/docs/STRATEGY_BLUEPRINT.md).

## Current Goal

Build a state-driven NIFTY options framework that answers five questions in order:

1. What market state are we in?
2. Is there any edge in this state?
3. Which strategy family fits this state?
4. What exact structure should be used?
5. What exit and risk policy matches that structure?

## Project Shape

- [STRATEGY_BLUEPRINT.md](/home/ubuntu/nifty/docs/STRATEGY_BLUEPRINT.md): first-principles design note
- [docs/STATE_MAP.md](/home/ubuntu/nifty/docs/STATE_MAP.md): working state definitions
- [docs/PLAYBOOKS.md](/home/ubuntu/nifty/docs/PLAYBOOKS.md): state-to-structure playbook mapping
- [docs/DATA_MODEL.md](/home/ubuntu/nifty/docs/DATA_MODEL.md): minimum inputs required for state and playbook decisions
- [docs/ARCHITECTURE.md](/home/ubuntu/nifty/docs/ARCHITECTURE.md): module ownership and runtime shape
- [docs/ROADMAP.md](/home/ubuntu/nifty/docs/ROADMAP.md): staged build plan
- [scripts](/home/ubuntu/nifty/scripts): canonical home for the rebuilt runtime code
- [archive](/home/ubuntu/nifty/archive): preserved old experiment

## Build Order

The rebuild should proceed in this order:

1. define the market states
2. map states to strategy families
3. define structure rules for each playbook
4. define entry and exit logic per playbook
5. define the minimum data model
6. only then start coding the runtime engine

## Current Status

This workspace has intentionally been reduced to a minimal starting point.

The old system is preserved in [archive](/home/ubuntu/nifty/archive), but it should be treated as reference material only, not as the template for the new design.
