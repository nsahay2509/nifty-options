# Architecture

This document defines the first implementation-oriented architecture for the rebuilt system.

Its purpose is to answer:

> Which modules own which responsibilities, and how should data flow through the system without collapsing back into one large, confusing script?

## Core Rule

All active implementation code for the rebuild should live under [scripts](/home/ubuntu/nifty/scripts).

The old archived code remains in [archive/scripts](/home/ubuntu/nifty/archive/scripts), but it is reference material only.

All broker-specific communication should live under [scripts/brokers](/home/ubuntu/nifty/scripts/brokers).

No non-broker module should construct broker URLs, headers, payloads, or parse broker-specific response shapes directly.

## Top-Level Runtime Flow

The rebuilt system should eventually run in this order:

1. load market session data
2. derive session references
3. classify market state
4. decide whether edge exists
5. select playbook
6. construct trade structure
7. execute or simulate the trade decision
8. record events and outcomes
9. report results by state, playbook, and structure

## Module Ownership

## 1. `scripts/config.py`

Owns:

- static configuration
- market session timings
- logging configuration
- cost model assumptions
- data-path configuration

Should not own:

- live business logic
- state classification logic
- trade execution logic

## 2. `scripts/log.py`

Owns:

- all logger creation
- formatter setup
- log-level defaults
- per-pathway logger names
- consistent event formatting

Should guarantee:

- every execution pathway gets a named logger
- critical events are always visible
- noisy internals can be suppressed or downgraded
- logs remain readable in plain text

## 3. `scripts/schema.py`

Owns the core domain objects.

Examples:

- `SpotCandle`
- `PriorDayLevels`
- `SessionReferences`
- `ExpiryInfo`
- `SessionSnapshot`
- `StateAssessment`
- `PlaybookDecision`
- `StructureProposal`
- `TradeRecord`

This is the canonical schema layer.

## 4. `scripts/brokers/`

Owns:

- broker interface contract
- broker request and response types
- credential loading
- broker-specific adapters such as Dhan

Recommended contents:

- `scripts/brokers/base.py`
- `scripts/brokers/types.py`
- `scripts/brokers/credentials.py`
- `scripts/brokers/dhan_client.py`
- `scripts/brokers/dhan_market_feed.py`

This directory is the only allowed boundary for direct broker communication.

## 5. `scripts/market_data.py`

Owns:

- base market-data subscriptions
- tick storage
- candle storage
- coordination of normalized ticks and candle builders

This module should be the first live market-data orchestration layer.

## 6. `scripts/candle_builder.py`

Owns:

- tick-to-candle aggregation
- 1-minute base candle construction
- derived multi-interval candle aggregation

## 7. `scripts/session_loader.py`

Owns:

- loading spot candles
- loading expiry calendar data
- loading instrument universe data
- loading premium snapshots
- constructing raw session inputs

Should not own:

- state classification
- playbook selection

## 8. `scripts/session_features.py`

Owns:

- prior-day level derivation
- opening range derivation
- session high and low so far
- realized-volatility proxy derivation
- other reusable session reference calculations

This module turns raw market data into structured session features.

## 9. `scripts/state_engine.py`

Owns:

- state classification
- ambiguity handling
- tradeability decision support

It should convert a `SessionSnapshot` into a `StateAssessment`.

This is where the logic from [STATE_MAP.md](/home/ubuntu/nifty/docs/STATE_MAP.md) should live.

## 10. `scripts/edge_filter.py`

Owns:

- deciding whether the current state is tradeable
- converting a valid state into either actionable edge or `NO_TRADE`

This prevents us from forcing action just because a state label exists.

## 11. `scripts/playbook_selector.py`

Owns:

- mapping state to preferred, allowed, and banned playbooks
- selecting a playbook for the current state

This is where the logic from [PLAYBOOKS.md](/home/ubuntu/nifty/docs/PLAYBOOKS.md) should live at the selection level.

## 12. `scripts/structure_builder.py`

Owns:

- choosing expiry for the chosen playbook
- choosing strikes
- choosing structure type
- estimating premium outlay or credit

This module turns a `PlaybookDecision` into a `StructureProposal`.

## 13. `scripts/cost_model.py`

Owns:

- brokerage assumptions
- statutory charge calculations
- exchange charge calculations
- trade-cost estimation

This should be the single source of truth for cost-adjusted reporting.

## 14. `scripts/trade_engine.py`

Owns:

- orchestration of the decision path
- simulated or live action routing
- entry and exit lifecycle handling

This module should remain thin.

It should coordinate modules, not absorb their logic.

## 15. `scripts/trade_recorder.py`

Owns:

- event logging for entries and exits
- normalized trade record persistence
- attaching state, playbook, and structure attribution to every trade

## 16. `scripts/reporting.py`

Owns:

- daily summaries
- state-wise summaries
- playbook-wise summaries
- cost-adjusted PnL summaries
- drawdown and quality reporting

## 17. `scripts/run_research.py`

Owns:

- running offline research and validation flows
- replaying historical sessions through the new architecture

This should remain clearly separate from the live or paper-trade runtime.

## Logging Architecture

The new system should have one logging module, not many inconsistent logger setups.

That module is [log.py](/home/ubuntu/nifty/scripts/log.py).

## Logging Principles

### 1. Log by pathway, not by chaos

Each major pathway should have its own logger name.

Suggested logger names:

- `session_loader`
- `session_features`
- `state_engine`
- `edge_filter`
- `playbook_selector`
- `structure_builder`
- `trade_engine`
- `trade_recorder`
- `reporting`

### 2. Log critical decisions, not every thought

We should always log:

- session start and end
- state classification result
- ambiguity or no-trade decision
- selected playbook
- proposed structure
- entry event
- exit event
- cost calculation summary
- trade record write
- reporting summary

We should avoid logging:

- repetitive low-signal loops
- unchanged state every cycle unless debugging is enabled
- raw payload spam by default

### 3. Prefer structured message shapes

Messages should be easy to scan later.

Example style:

```text
STATE | state=TrendContinuation confidence=high dte=3 phase=mid_session
PLAYBOOK | selected=bull_call_spread alternatives=long_call,no_trade reason=trend_clean_iv_elevated
TRADE_ENTRY | trade_id=... playbook=bull_call_spread state=TrendContinuation expiry=... strikes=...
TRADE_EXIT | trade_id=... reason=trend_break gross_pnl=... cost=... net_pnl=...
```

### 4. Keep default logs concise

Default logs should tell the story of:

- what the system saw
- what it decided
- why it acted or did not act
- how the trade ended

Detailed debugging should be opt-in.

### 5. Record all critical events durably

Plain text logs should be complemented by structured trade-event records.

The log tells the narrative.

The trade record tells the data truth.

We need both.

## Suggested Directory Ownership

The rebuild should use this structure:

```text
/home/ubuntu/nifty/
  README.md
  docs/
  scripts/
    __init__.py
    config.py
    log.py
    schema.py
    brokers/
      __init__.py
      base.py
      types.py
      credentials.py
      dhan_client.py
      dhan_market_feed.py
    market_data.py
    candle_builder.py
    session_loader.py
    session_features.py
    state_engine.py
    edge_filter.py
    playbook_selector.py
    structure_builder.py
    cost_model.py
    trade_engine.py
    trade_recorder.py
    reporting.py
    run_research.py
  tests/
  archive/
```

## First Implementation Order

The first coding pass should not try to create everything at once.

Recommended order:

1. `scripts/log.py`
2. `scripts/config.py`
3. `scripts/schema.py`
4. `scripts/session_features.py`
5. `scripts/state_engine.py`
6. `scripts/playbook_selector.py`
7. `scripts/cost_model.py`
8. `scripts/trade_recorder.py`
9. `scripts/reporting.py`
10. `scripts/trade_engine.py`

## Non-Negotiable Rule

No module should silently absorb more than one major responsibility.

If a file starts mixing:

- data loading
- feature derivation
- state classification
- playbook selection
- structure building
- trade execution
- reporting

then we are rebuilding the same confusion we deliberately removed.

## Next Required Step

The next step should be to create the initial `scripts/` skeleton around this architecture and give `scripts/log.py` a clean default implementation.
