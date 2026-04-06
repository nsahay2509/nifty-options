# State Map

This document defines the first working market-state map for the rebuilt NIFTY options framework.

Its purpose is not to predict direction by itself. Its purpose is to answer a more practical question:

> What kind of market are we dealing with right now, and what option playbooks are naturally compatible with it?

## Design Goal

The state map should be:

- small enough to be understandable
- rich enough to separate meaningfully different market conditions
- strict enough to allow `NO_TRADE`
- practical enough to map directly into strategy families

This is a working version, not a final doctrine. It should be refined only after structured observation and testing.

## Core Rule

The state engine should not try to express everything in one label.

Instead, it should classify the market in layers:

1. expiry-cycle context
2. opening context
3. directional structure
4. realized volatility behavior
5. tradeability

Then it should assign one top-level state from this document.

## The Eight Working States

The first working state map has eight top-level states:

1. Gap Continuation
2. Gap Mean Reversion
3. Trend Continuation
4. Controlled Range
5. Volatility Expansion
6. Choppy Transition
7. Expiry Compression
8. Expiry Gamma Expansion

This is intentionally small. The goal is to separate different trading environments without overfitting.

## Classification Order

The state engine should classify in this order:

1. Check whether the market is in a special expiry condition.
2. Check whether the day opened with a meaningful gap.
3. Check whether price is trending cleanly or rotating.
4. Check whether volatility is contained or expanding.
5. Check whether the environment is tradeable or noisy.

This order matters because expiry conditions and gap conditions can dominate everything else.

## Shared Definitions

These terms should be interpreted consistently across all states.

### Clean trend

A clean trend means:

- directional movement is persistent
- pullbacks are shallow or structured
- breakout levels are respected
- reversals are not immediately undoing the move

### Controlled range

A controlled range means:

- price is oscillating within visible boundaries
- realized movement is contained
- repeated break attempts fail
- there is no strong directional follow-through

### Volatility expansion

A volatility expansion means:

- bar ranges are widening
- reversals can still be sharp, but movement is materially larger than quiet conditions
- realized movement is increasing relative to the recent baseline

### Choppy transition

A choppy transition means:

- directional signals flip often
- breakout attempts fail quickly
- the market lacks clear containment and lacks clean continuation
- this is often the most dangerous state for overtrading

## State 1: Gap Continuation

### Plain-language description

The market opens with a meaningful gap and then shows evidence that the gap is being accepted rather than faded.

### Typical evidence

- clear opening gap up or gap down
- early range breaks in the direction of the gap
- little interest in filling the gap
- pullbacks hold above or below the opening structure
- momentum remains aligned with the opening move

### Common failure mode

The apparent continuation is actually an opening trap and the market rotates back into the prior range.

### Preferred strategy families

- long call
- long put
- bull call spread
- bear put spread
- directional intraday scalps

### Allowed strategy families

- narrowly defined debit spreads

### Banned or strongly discouraged

- naked short premium
- iron condor
- iron fly
- mean-reversion structures against the accepted gap

### `NO_TRADE` guidance

Not common if continuation is confirmed.

Common if the gap is large but acceptance is unclear.

## State 2: Gap Mean Reversion

### Plain-language description

The market opens with a meaningful gap, but the gap is not accepted. Price starts moving back toward the prior session value area.

### Typical evidence

- clear opening gap
- failure to extend after the open
- early rejection of the opening move
- movement back toward prior-day range or key reference zone
- fading momentum in the gap direction

### Common failure mode

The gap-fade attempt gets trapped and the original gap direction reasserts itself.

### Preferred strategy families

- long call or long put in the direction of the gap fill
- debit spreads in the direction of reversion
- short holding-period reversal scalps

### Allowed strategy families

- small defined-risk reversal structures

### Banned or strongly discouraged

- premium-selling structures too early
- continuation trades after the gap has clearly failed

### `NO_TRADE` guidance

Common when the market is unstable and neither the gap continuation nor the gap fill is clean.

## State 3: Trend Continuation

### Plain-language description

This is a non-gap or post-open market that is trending cleanly in one direction and continuing to respect that direction.

### Typical evidence

- sustained higher highs and higher lows, or lower highs and lower lows
- pullbacks are orderly
- no repeated rejection of breakout levels
- directional conviction remains intact through multiple bars
- realized movement is directional, not random

### Common failure mode

The trend appears strong but is actually late and near exhaustion, causing entries to be taken just before reversal or compression.

### Preferred strategy families

- long call
- long put
- bull call spread
- bear put spread

### Allowed strategy families

- directional scalp structures
- partial profit-taking trend structures

### Banned or strongly discouraged

- short straddle
- short strangle
- iron condor
- fade-the-trend structures

### `NO_TRADE` guidance

Not common when the trend is clean.

Common when the trend is already extended and reward-to-risk has become poor.

## State 4: Controlled Range

### Plain-language description

The market is moving inside a visible and respected range. Breakouts fail, movement stays contained, and time decay may matter more than directional conviction.

### Typical evidence

- repeated rejection near upper and lower boundaries
- no strong directional expansion
- intraday realized range remains controlled
- price returns toward the middle of the range after excursions
- breakout attempts do not persist

### Common failure mode

The range suddenly breaks into expansion, trapping premium sellers and mean-reversion trades.

### Preferred strategy families

- call credit spread
- put credit spread
- iron condor
- iron fly
- limited-risk premium-selling structures

### Allowed strategy families

- short mean-reversion scalps
- conservative range-bound structures

### Banned or strongly discouraged

- aggressive long options without breakout confirmation
- trend continuation structures

### `NO_TRADE` guidance

Not common when containment is clean.

Common when the range is too narrow to justify premium selling after costs.

## State 5: Volatility Expansion

### Plain-language description

The market is no longer quiet. Movement has materially expanded relative to the recent baseline, but direction may be unstable or still forming.

### Typical evidence

- larger bar ranges
- faster movement through levels
- realized volatility rising sharply versus recent bars
- wider intraday swings
- repeated large moves, even if directional conviction is still forming

### Common failure mode

Traders mistake noisy expansion for a clean trend and overcommit to directional structures at the wrong moment.

### Preferred strategy families

- long straddle
- long strangle
- delayed directional entry after confirmation
- defined-risk directional spread once structure becomes clearer

### Allowed strategy families

- selective long-option structures

### Banned or strongly discouraged

- naked short premium
- wide iron condors
- passive theta-selling structures that assume containment

### `NO_TRADE` guidance

Common when realized expansion is high but the market is still structurally unreadable.

## State 6: Choppy Transition

### Plain-language description

The market is not clearly trending and not cleanly ranging. Signals flip, structure is unstable, and trade quality is usually poor.

### Typical evidence

- frequent directional reversals
- breakout attempts fail quickly
- no persistent follow-through
- no stable containment either
- price alternates between momentum and rejection

### Common failure mode

The system keeps finding trades because something is always moving, but the market is actually offering no reliable edge.

### Preferred strategy families

- `NO_TRADE`

### Allowed strategy families

- only very selective small-risk structures if a clear micro-setup exists

### Banned or strongly discouraged

- frequent re-entry systems
- trend-following structures
- premium-selling based on weak containment
- large directional positions

### `NO_TRADE` guidance

Very common.

This state should often resolve to no trade.

## State 7: Expiry Compression

### Plain-language description

This is a pre-expiry or expiry-adjacent environment where price remains relatively contained and the dominant feature is premium decay rather than directional expansion.

### Typical evidence

- market remains near a few dominant strikes
- realized movement is modest relative to expected movement
- repeated pullback toward a central zone
- time decay and pinning behavior appear more important than trend

### Common failure mode

The market looks pinned until a sharp late move breaks containment and punishes short gamma positions.

### Preferred strategy families

- defined-risk credit spreads
- iron condor
- iron fly
- tightly controlled premium-selling structures

### Allowed strategy families

- short holding-period expiry decay structures

### Banned or strongly discouraged

- naked short premium without strong safeguards
- long options purchased too late without movement edge

### `NO_TRADE` guidance

Common when the expected edge from decay is too small after cost or when pinning behavior is not clean enough.

## State 8: Expiry Gamma Expansion

### Plain-language description

This is an expiry-adjacent environment where price behavior becomes sharp, unstable, and highly sensitive to strike zones. The market can move quickly and reverse quickly.

### Typical evidence

- abrupt directional bursts
- violent reversals near key strikes
- high sensitivity to local price movement
- large moves relative to immediate prior bars
- unstable intraday structure despite being near expiry

### Common failure mode

A trader assumes expiry will behave like quiet decay, but the market turns into a high-gamma directional and reversal battle.

### Preferred strategy families

- very short holding-period directional scalps
- small defined-risk directional spreads
- selective long options when movement edge is clear

### Allowed strategy families

- highly tactical expiry structures

### Banned or strongly discouraged

- passive premium selling
- wide short-volatility structures
- slow reaction systems

### `NO_TRADE` guidance

Common unless the setup is extremely clear.

## Strategy Mapping Summary

This is the high-level intended mapping:

- Gap Continuation: directional long-option or debit-spread playbooks
- Gap Mean Reversion: reversal playbooks with tight risk
- Trend Continuation: directional long-option or debit-spread playbooks
- Controlled Range: defined-risk short-premium playbooks
- Volatility Expansion: long-volatility or delayed-confirmation playbooks
- Choppy Transition: usually no trade
- Expiry Compression: expiry decay playbooks with defined risk
- Expiry Gamma Expansion: tactical scalp and defined-risk directional playbooks

## The Role of `NO_TRADE`

`NO_TRADE` is not a fallback or an embarrassment.

It is a primary system output in at least these situations:

- the market is in Choppy Transition
- the state is ambiguous between continuation and reversal
- the edge is too small after costs
- expiry behavior is unstable but not directional enough
- range containment is too weak for premium selling
- directional structure is too late for long options

## State Boundaries Matter More Than Tiny Precision

At this stage, the system does not need perfect mathematical separation between states.

It needs useful practical separation.

The first objective is not:

> classify with maximum sophistication

The first objective is:

> separate market conditions that demand different option structures

That is enough to begin playbook design.

## Next Required Design Step

The next document should define playbooks for each state:

- what is preferred
- what is allowed
- what is banned
- what exact structures belong in each case

That work should be done before writing runtime trading logic.
