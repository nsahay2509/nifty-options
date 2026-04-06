# Playbooks

This document converts the working state map into concrete option playbooks.

Its job is to answer:

> Given a known market state, what structures should we prefer, what should we allow, what should we ban, and how should we think about entry, exit, and risk?

This is still a design document, not an implementation document.

## How To Read This Document

Each state section below contains:

- preferred playbooks
- allowed but secondary playbooks
- banned or discouraged playbooks
- strike-selection posture
- expiry posture
- entry posture
- exit posture
- risk posture

The goal is not to create maximum optionality.

The goal is to reduce confusion and stop mixing incompatible structures with incompatible market states.

## Shared Playbook Families

The system will use a small set of strategy families.

### Directional long-premium

- long call
- long put

Best use:

- when directional movement is expected to continue fast enough to overcome theta

### Directional debit spreads

- bull call spread
- bear put spread

Best use:

- when direction is favorable but outright premium may be too expensive

### Defined-risk short-premium

- call credit spread
- put credit spread
- iron condor
- iron fly

Best use:

- when containment or decay edge is stronger than directional edge

### Long-volatility

- long straddle
- long strangle

Best use:

- when realized movement is expected to exceed the implied movement being paid

### Tactical scalps

- short holding-period directional structures
- fast expiry-day structures

Best use:

- when timing is more important than longer intraday holding

### No-trade

- explicit stay-flat decision

Best use:

- when state is real but edge is absent
- when state is ambiguous
- when structure edge is too small after costs

## State 1: Gap Continuation

### Preferred playbooks

- long call for accepted bullish gap
- long put for accepted bearish gap
- bull call spread
- bear put spread
- tactical continuation scalp

### Allowed but secondary

- narrowly defined debit spreads

### Banned or discouraged

- iron condor
- iron fly
- short straddle
- early gap-fade structures
- passive short-premium trades

### Strike-selection posture

- near-ATM or slightly ITM for outright long options
- near-ATM to modestly OTM for debit spreads
- avoid very far OTM options unless the move is expected to accelerate materially

### Expiry posture

- same-week expiry can be used for intraday continuation only if theta is acceptable
- otherwise prefer enough remaining life to avoid overpaying for near-expiry noise

### Entry posture

- wait for acceptance, not just the gap itself
- prefer entry after opening balance break or successful retest
- avoid chasing the very first impulse unless the setup is extremely clean

### Exit posture

- exit on failure of continuation structure
- exit on break of opening support or resistance that defined acceptance
- take partial profits into strong extension
- do not let a continuation trade turn into a gap-fade hope trade

### Risk posture

- normal directional sizing when continuation is clear
- smaller size if the gap is already very stretched
- no premium-selling overlay against the gap unless state changes first

## State 2: Gap Mean Reversion

### Preferred playbooks

- long call or long put in the direction of the gap fill
- debit spread in the direction of reversion
- reversal scalp

### Allowed but secondary

- very small defined-risk reversal structure

### Banned or discouraged

- premium selling in the first unstable phase
- continuation trades after clear rejection
- wide structures that need slow stabilization

### Strike-selection posture

- ATM or slightly ITM for reversals
- if using a spread, keep it reasonably tight because gap-fill trades can lose speed after the first reversion leg

### Expiry posture

- prefer expiries that do not overcharge theta for a short-lived move
- very near expiry only if the setup is scalp-like and highly tactical

### Entry posture

- require evidence that the gap has failed
- prefer rejection plus re-entry into prior value area
- avoid trying to catch the exact turning point

### Exit posture

- exit if the original gap direction reasserts itself
- take profits into the fill zone rather than demanding full-day reversal
- treat the prior session references as natural exit areas

### Risk posture

- smaller than clean trend continuation trades
- fast invalidation
- no averaging into failed reversals

## State 3: Trend Continuation

### Preferred playbooks

- long call
- long put
- bull call spread
- bear put spread

### Allowed but secondary

- directional scalp
- staged trend participation with partial exits

### Banned or discouraged

- short straddle
- short strangle
- condors
- fade structures against the active trend

### Strike-selection posture

- ATM or slightly ITM for cleaner trend participation
- moderate-width debit spreads when IV is elevated
- avoid very far OTM lottery structures

### Expiry posture

- same-week if the move is expected soon
- next-week or slightly longer if the trend is expected to persist beyond one impulse

### Entry posture

- prefer entries on pullback hold, breakout hold, or continuation after pause
- avoid entering at the tail end of a very extended run

### Exit posture

- exit on clear trend break
- reduce exposure into exhaustion signals
- do not hold long premium after the move loses speed and theta becomes dominant

### Risk posture

- this is one of the more natural states for directional risk
- size should still reduce when the trend is late or overextended

## State 4: Controlled Range

### Preferred playbooks

- call credit spread
- put credit spread
- iron condor
- iron fly

### Allowed but secondary

- small mean-reversion scalp
- range fade with tight risk

### Banned or discouraged

- aggressive long calls or puts without breakout confirmation
- trend-following playbooks
- large premium exposure when the range is too narrow to cover costs

### Strike-selection posture

- short strikes should sit outside the repeatedly respected range
- prefer defined-risk structures over naked short premium
- the structure should assume containment, not hope for it

### Expiry posture

- short-dated structures may be attractive if containment is strong
- do not choose expiry so close that one small break destroys the whole edge

### Entry posture

- enter only after range boundaries have been tested and respected
- avoid initiating premium-selling just as the market is beginning to widen

### Exit posture

- exit when the range stops behaving like a range
- cut quickly on credible breakout
- take profits once enough decay is captured rather than insisting on full expiration value

### Risk posture

- defined risk is strongly preferred
- this state can become dangerous quickly if it transitions into expansion

## State 5: Volatility Expansion

### Preferred playbooks

- long straddle
- long strangle
- delayed directional long option after structure clarifies
- directional debit spread after confirmation

### Allowed but secondary

- highly selective outright long call or long put

### Banned or discouraged

- iron condor
- iron fly
- passive credit spreads that rely on containment
- short gamma structures without exceptional justification

### Strike-selection posture

- for long-vol trades, avoid overpaying for wings that need extreme movement
- for delayed directional trades, use strikes that still give useful delta without requiring a perfect move

### Expiry posture

- enough time for realized movement to develop
- avoid buying extremely short-dated premium unless the move is already unfolding and the trade is tactical

### Entry posture

- do not confuse random violence with tradeable edge
- enter either for movement itself or after directional structure becomes readable
- if uncertainty remains too high, stay flat

### Exit posture

- exit long-vol if realized movement stalls
- exit directional structures if expansion continues but direction degrades into chop
- take profits into rapid movement instead of waiting for perfection

### Risk posture

- risk should be tightly controlled because expansion can still be chaotic
- this is often a state for patience rather than frequent action

## State 6: Choppy Transition

### Preferred playbooks

- no trade

### Allowed but secondary

- only rare small-risk tactical structures when a very specific setup is present

### Banned or discouraged

- repeated re-entry systems
- trend-following structures
- range-selling structures based on weak containment
- oversized directional trades

### Strike-selection posture

- not applicable in most cases because this state should usually not produce a trade

### Expiry posture

- not applicable in most cases because trade avoidance is preferred

### Entry posture

- extremely selective
- do not trade simply because price is moving

### Exit posture

- very fast invalidation if a tactical trade is taken

### Risk posture

- minimal or zero
- this is the state where discipline matters most

## State 7: Expiry Compression

### Preferred playbooks

- call credit spread
- put credit spread
- iron condor
- iron fly
- tightly defined expiry-decay structures

### Allowed but secondary

- short holding-period premium-selling structures with defined risk

### Banned or discouraged

- naked short premium without strict controls
- late long-option chasing without movement edge

### Strike-selection posture

- structure should be built around the dominant containment zone
- short strikes should sit beyond the expected pin or stable value area
- defined wings are strongly preferred

### Expiry posture

- this state is specifically about near-expiry behavior
- same-expiry structures are natural, but only with strict containment evidence

### Entry posture

- wait until containment is visible
- do not enter merely because expiry is near
- require evidence that the market is decaying, not coiling for a violent move

### Exit posture

- exit if containment breaks
- take profits once meaningful decay is harvested
- do not stay oversized into late-session instability

### Risk posture

- moderate but defined
- the whole edge here comes from containment and time decay, so risk must be cut quickly if that assumption fails

## State 8: Expiry Gamma Expansion

### Preferred playbooks

- very short holding-period directional scalp
- small defined-risk directional spread
- selective long call or long put when movement is clearly asymmetric

### Allowed but secondary

- highly tactical expiry structures with fast response

### Banned or discouraged

- passive premium-selling
- wide short-volatility structures
- slow discretionary holds

### Strike-selection posture

- stay near the active strike zone
- prioritize responsiveness over cheapness
- avoid structures that need too much time to work

### Expiry posture

- this is inherently near-expiry behavior
- same-day and next-expiry structures may be used, but only tactically

### Entry posture

- require very clear local structure
- timing matters more than broad daily bias
- if the move is unclear, do not trade

### Exit posture

- fast profit-taking
- fast invalidation
- do not convert expiry scalp trades into longer holds

### Risk posture

- small size
- strict stops
- high selectivity

## Cross-State Strike and Expiry Rules

These broad rules should apply across all states.

### Prefer simple structures first

The system should first prove edge with simpler structures before becoming too clever.

Examples:

- long call or long put before exotic directional structures
- credit spreads before naked short premium
- iron condors only after range quality is proven

### Use defined risk by default

Especially in the rebuild phase, defined-risk structures should be preferred over unlimited-risk short premium.

### Match expiry to thesis duration

- short intraday thesis: short-dated is acceptable
- directional thesis needing time: use more time
- decay thesis: use near-expiry only when containment evidence is strong

### Do not let cheap premium dictate structure

Cheap far OTM options often create false comfort.

The structure should be chosen for thesis quality, not for low absolute premium.

## Cross-State Entry Principles

These should apply across all playbooks.

### Entry should follow state confirmation

Do not trade because a possible state might exist.

Trade only after the state is sufficiently confirmed.

### Entry should match structure logic

- long premium needs movement edge
- short premium needs containment edge
- long volatility needs realized-move edge

### Ambiguity should default to smaller size or no trade

When two states are competing and neither is dominant, the default should lean toward caution.

## Cross-State Exit Principles

These should apply across all playbooks.

### Exit on thesis failure, not only on pain

The system should exit when the reason for the trade is no longer valid.

### Take the type of profit the structure was built for

- directional trades should monetize movement
- decay trades should monetize containment and time decay
- expiry scalps should monetize speed

### Avoid structure drift

Do not let:

- a scalp become a swing
- a continuation trade become a hope trade
- a decay structure become a disaster hold

## Cross-State Risk Principles

### Risk should depend on state quality

- clean state: normal size
- ambiguous state: smaller size
- choppy state: no trade or near-zero size

### The rebuild should optimize for survival and clarity first

Before we optimize for return, we should optimize for:

- understanding
- repeatability
- structure-state fit
- controlled losses

## Next Required Design Step

The next document or task should define the minimum data model required to classify these states and select these playbooks.

That means deciding what inputs are mandatory:

- spot candles
- prior-day references
- expiry calendar
- option chain
- OI and IV data
- intraday reference levels

Only after that should we begin coding the state engine itself.
