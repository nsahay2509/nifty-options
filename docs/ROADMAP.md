# Roadmap

## Current Operational Milestone — 2026-04-07

- state-driven runtime, reporting, and monitor are now operational
- market-hours automation is enabled with holiday/weekend-aware start and stop behavior
- the UI has been simplified so the execution mode is shown separately from the trading logic
- reporting and trade-recording now preserve realised P&L, lifecycle timing, and leg details
- configurable state-confirmation gating is now in place to reduce overtrading
- detailed change rationale and results are now tracked in `docs/PROGRESS_LOG.md`
- the next implementation step is to observe tomorrow's run and decide whether additional entry/exit filters are actually needed

## Phase 1: Design

1. finalize the state map
2. map each state to suitable strategy families
3. define banned structures for each state
4. define state-specific data requirements

## Phase 2: Playbook Design

1. define each strategy family as a playbook
2. define strike and expiry selection rules
3. define entry confirmation rules
4. define exit and risk rules

## Phase 3: Data Model

1. define the minimum candle data needed
2. define expiry calendar inputs
3. define option-chain and IV/OI requirements
4. define research and reporting outputs

## Phase 4: Implementation

1. build the state engine
2. build the playbook selector
3. build structure-specific execution rules
4. build reporting around state and playbook attribution

## Rule For The Rebuild

Do not start coding the runtime engine before the design answers:

- what states exist
- which strategies fit each state
- when we should not trade
