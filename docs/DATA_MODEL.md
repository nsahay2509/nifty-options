# Data Model

This document defines the minimum data model required to support the rebuilt NIFTY options framework.

Its purpose is to answer:

> What exact inputs must exist for the system to classify state, choose a playbook, structure a trade, and evaluate results properly?

This is a design document. It defines what data the system should own before we start implementing the engine.

## Design Principle

The rebuild should not wait for perfect data before it becomes useful.

Instead, data requirements should be layered:

1. mandatory now
2. strongly recommended soon
3. optional later

That lets us start with a disciplined core while still leaving room for richer option-context later.

## Data Layers

### Layer 1: Mandatory Now

Without this layer, the rebuild should not proceed.

This is the minimum required to:

- classify basic market states
- choose among the first set of playbooks
- define entries and exits
- report trade outcomes correctly

### Layer 2: Strongly Recommended Soon

This layer is not required to start, but it is required to improve playbook quality and avoid flying blind in expiry and premium-selling states.

### Layer 3: Optional Later

This layer improves sophistication and research quality, but should not block early implementation.

## Layer 1: Mandatory Now

## 1. Spot Candle Data

This is the core market-structure input.

### Purpose

Needed for:

- gap detection
- trend identification
- range identification
- volatility expansion detection
- intraday structure analysis

### Required fields

- `timestamp`
- `open`
- `high`
- `low`
- `close`

### Required granularity

- 1-minute candles

### Required session behavior

- trading-day segmentation
- clear session start and end
- no mixing across days without explicit handling

### Notes

Volume is useful, but not mandatory for the first build if trustworthy volume is not available.

## 2. Prior-Day Reference Levels

These should be derived and stored explicitly for each trading day.

### Purpose

Needed for:

- gap classification
- gap-fill logic
- opening acceptance vs rejection logic
- intraday contextual references

### Required fields

- previous day open
- previous day high
- previous day low
- previous day close
- previous day range
- previous day midpoint

### Notes

These can be derived from spot candles, but they should still be treated as first-class inputs in the state engine.

## 3. Session Reference Levels

These are intraday structural references.

### Purpose

Needed for:

- opening imbalance detection
- opening range break logic
- pullback and continuation logic
- range boundary logic

### Required fields

- opening range high
- opening range low
- intraday high so far
- intraday low so far
- session midpoint

### Notes

The exact opening-range duration can be chosen later, but the concept must exist in the model.

## 4. Expiry Calendar

This is mandatory because expiry-cycle context is a first-class part of the design.

### Purpose

Needed for:

- days-to-expiry calculation
- expiry-eve classification
- expiry-day classification
- playbook restrictions by expiry proximity

### Required fields

- instrument family
- expiry date
- weekly vs monthly tag
- days to expiry from session date

### Notes

For this rebuild, the minimum need is reliable NIFTY expiry dates and a clean `days_to_expiry` calculation.

## 5. Instrument Universe / Tradable Structures

The system cannot choose a playbook unless it knows what actual tradable contracts exist.

### Purpose

Needed for:

- strike selection
- expiry selection
- mapping playbooks to real contracts

### Required fields

- symbol or instrument identifier
- strike
- expiry
- option type (`CE` / `PE`)
- lot size

### Notes

This can begin as a clean contract-resolution layer.

## 6. Option Premium Snapshot at Decision Time

Even the first build should know the premium it is paying or receiving when selecting a structure.

### Purpose

Needed for:

- deciding between long option and debit spread
- avoiding overpriced structures
- realistic trade construction
- realistic cost and PnL reporting

### Required fields

- timestamp
- instrument identifier
- last traded price or usable quote proxy

### Notes

For the first version, last traded price may be acceptable if better quote data is unavailable.

## 7. Trade Event Record

Every trade should be recorded in a normalized format.

### Purpose

Needed for:

- post-trade analysis
- cost accounting
- state attribution
- playbook attribution
- system debugging

### Required fields

- `trade_id`
- `timestamp_entry`
- `timestamp_exit`
- `state_at_entry`
- `playbook`
- `structure_type`
- `underlying_context`
- `expiry`
- `strike_or_strikes`
- `side`
- `quantity`
- `entry_price_or_prices`
- `exit_price_or_prices`
- `gross_pnl`
- `fees_and_costs`
- `net_pnl`
- `exit_reason`

### Notes

The new system should treat state and playbook attribution as mandatory, not optional.

## 8. Cost Model Inputs

The previous system already taught us that cost awareness is necessary from the beginning.

### Purpose

Needed for:

- realistic net PnL
- deciding whether a state has edge after costs
- selecting structures with the right turnover profile

### Required fields

- brokerage assumptions
- statutory charge assumptions
- exchange charge assumptions
- stamp duty assumptions
- STT assumptions

### Notes

These can be centrally configured, but the system must use them consistently in reporting.

## Layer 2: Strongly Recommended Soon

## 9. Option Chain Snapshot

This becomes important once the system wants to move beyond simple spot-driven inference.

### Purpose

Needed for:

- identifying likely pin zones
- contextualizing strikes
- understanding local structure around ATM

### Recommended fields

- timestamp
- strike
- call premium
- put premium
- open interest
- change in open interest
- volume

### Why it matters

States like Expiry Compression and Expiry Gamma Expansion become much easier to distinguish when the nearby chain is visible.

## 10. Implied Volatility Context

### Purpose

Needed for:

- choosing between long-vol and short-vol structures
- deciding when long options are too expensive
- distinguishing movement edge from overpayment

### Recommended fields

- ATM IV
- skew by nearby strikes
- IV percentile or recent IV rank proxy

### Why it matters

Without IV context, the system may classify direction correctly but still choose the wrong structure.

## 11. Time-of-Day Context

This can be derived, but it should still be represented explicitly.

### Purpose

Needed for:

- opening-state logic
- post-open transition logic
- afternoon drift logic
- late-day expiry behavior

### Recommended fields

- minutes since open
- session phase label

### Example session phases

- open
- early trend window
- mid-session
- afternoon
- late session

## 12. Derived Volatility Features

### Purpose

Needed for:

- distinguishing Controlled Range from Volatility Expansion
- sizing risk
- selecting long-vol vs short-vol playbooks

### Recommended fields

- rolling intraday range
- realized volatility proxy
- opening range size
- expansion vs baseline ratio

## Layer 3: Optional Later

## 13. Market Breadth / Index Context

### Possible uses

- confirming whether NIFTY movement is broad-based or narrow
- filtering trend continuation quality

### Example fields

- sector breadth
- advance/decline measures
- bank/index confirmation

## 14. Order Flow / Microstructure Context

### Possible uses

- better expiry scalps
- better tactical reversals

### Example fields

- bid/ask spread
- quote imbalance
- order-book pressure

### Notes

Useful, but absolutely not required for the first build.

## 15. Event Calendar

### Possible uses

- avoiding high-risk scheduled-event windows
- distinguishing normal expansion from event-driven expansion

### Example fields

- RBI policy days
- major macro releases
- large market-wide scheduled events

## Core Domain Objects

The new system should eventually represent these as explicit domain models.

## 1. SessionSnapshot

One object representing the current state of the market session.

### Minimum contents

- current timestamp
- current spot candle
- prior-day references
- session references
- expiry context
- realized-volatility context

## 2. StateAssessment

One object representing the current classified state.

### Minimum contents

- top-level state
- supporting evidence
- ambiguity level
- tradeability score or label

## 3. PlaybookDecision

One object representing the chosen playbook or no-trade result.

### Minimum contents

- chosen playbook
- reason for selection
- banned alternatives
- confidence or quality label

## 4. StructureProposal

One object representing the specific structure to trade.

### Minimum contents

- structure type
- expiry chosen
- strike selection
- estimated premium outlay or credit
- expected holding style

## 5. TradeRecord

One object representing the full lifecycle of a trade.

### Minimum contents

- entry data
- exit data
- state attribution
- playbook attribution
- structure attribution
- cost-adjusted result

## What We Can Build With Only Layer 1

With Layer 1 alone, we can build a credible first engine for:

- Gap Continuation
- Gap Mean Reversion
- Trend Continuation
- Controlled Range
- basic Choppy Transition filtering

We can also begin simple structure selection between:

- long option
- debit spread
- credit spread
- no trade

That is enough to start the rebuild.

## What Still Needs Layer 2

These parts become materially better once Layer 2 exists:

- Expiry Compression
- Expiry Gamma Expansion
- long-volatility playbooks
- premium-selling quality control
- better structure selection under IV differences

## First Build Recommendation

The first implementation should not attempt to support every state equally.

It should prioritize the states that can be supported with strong evidence from the minimum data model.

Recommended first-build priority:

1. Trend Continuation
2. Gap Continuation
3. Gap Mean Reversion
4. Controlled Range
5. Choppy Transition as a no-trade filter

Then add:

6. Volatility Expansion
7. Expiry Compression
8. Expiry Gamma Expansion

## Data Quality Rules

Even a good model fails if the data is weak.

The system should enforce these rules:

- timestamps must be consistent
- candle sessions must not be mixed
- expiry dates must be reliable
- option premiums must be attached to actual trade decisions
- trade logs must always carry state and playbook attribution
- missing critical fields should block strategy selection rather than allow silent degradation

## Next Required Design Step

The next step should define the actual domain schema and folder-level ownership for these objects.

In practical terms, that means deciding:

- which files or modules will own session data
- which modules will classify state
- which modules will select playbooks
- which modules will construct structures
- which modules will report outcomes

Only after that should we begin the first implementation pass.
