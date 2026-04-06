# NIFTY Option Experiment - Current Status

**Last updated:** 2026-04-02  
**Project root:** `/home/ubuntu/nifty`

---

## 1) Purpose of the current setup

This repository is currently a **paper-trading experiment framework** for NIFTY options.

The practical question being tested is:

> **Can this regime-based option method produce profit consistently over trading days and, later, over weeks?**

At present, the system is best described as an **intraday paper-trading evaluator**, not yet a full multi-day or weekly positional system.

---

## 2) What the present code is doing

### Main runtime flow

1. **`nifty_evaluator.py`**
   - runs once every minute + 5 seconds
   - active during market hours
   - orchestrates the full cycle

2. **`scripts/update_nifty_spot.py`**
   - fetches the latest 1-minute NIFTY spot candle from Dhan
   - stores candles in `data/spot/YYYY-MM-DD.jsonl`

3. **`scripts/regime_classifier.py`**
   - looks at the last 25 candles
   - computes simple trend features:
     - `direction_score`
     - `bias`
     - `compression_score`
     - `window_range`
   - outputs regimes such as:
     - `SELL_PE`
     - `SELL_CE`
     - `WAIT`

4. **`scripts/signal_engine.py`**
   - adds persistence and minimum time gap logic
   - prevents immediate signal churn

5. **`scripts/paper_trade_engine.py`** and **`scripts/paper_trade_engine_buy.py`**
   - simulate option entries/exits in paper mode
   - `SELL` side sells the ATM option matching the trend direction
   - `BUY` side buys the opposite option expression from the same signal

6. **`scripts/paper_mtm_engine.py`** and **`scripts/paper_mtm_engine_buy.py`**
   - calculate mark-to-market PnL
   - write results into CSVs in `data/results/`

7. **`monitoring_web.py`**
   - shows a read-only dashboard for runtime monitoring

---

## 3) Verified current status as of 2026-04-02

The following was verified from the running setup:

- **Test suite:** `pytest -q` -> **25 passed in 1.09s**
- **Live processes:** both of these are running:
  - `nifty_evaluator.py`
  - `monitoring_web.py`
- **Dashboard state (`data/dashboard_state.json`):**
  - `updater_ok: true`
  - `confirmed_regime: WAIT`
  - no open positions on either side
  - current live PnL on both sides = `0.0`

### Latest observed reporting state

- `daily_summary_combined.csv` last visible combined result:
  - **2026-03-27**
  - **62 trades**
  - **4 wins / 58 losses**
  - **net PnL = -3515.0**

### Latest realised PnL snapshots saved in state files

- `data/pnl_state.json` (SELL side, 2026-04-01): about **₹855** realised
- `data/pnl_state_buy.json` (BUY side, 2026-04-01): about **₹1007.5** realised

This suggests the runtime system is active, but the daily summary/reporting outputs are not fully aligned with the latest state.

---

## 4) Important conclusion about the current experiment

### Current system is **intraday**, not positional

In the trade config, the system currently forces same-day exits:

- `no_new_entry_after = 15:15`
- `force_exit_time = 15:25`

This means the present setup is testing:

> **"Can an intraday trend-based NIFTY option method make money?"**

It is **not yet testing**:

> **"Can this option method make money over multiple days or weeks?"**

So the framework is useful, but it still needs changes if the intended experiment is genuinely about **days/weeks profitability**.

---

## 5) Main gaps in the present setup

### A. Strategy/data gap
The signal logic is based mainly on **spot price movement**, not on richer option-specific data.

Current limitations:
- no option chain feature analysis
- no IV / OI / option volume logic
- no real VWAP-based logic yet
- spot updater writes `volume: 0`, so volume-based research is not truly supported right now

### B. Holding-period mismatch
The system exits intraday, so it cannot evaluate:
- overnight gap risk
- decay over multiple days
- weekly expiry behavior
- positional trade management

### C. Reporting freshness issue
The CSV summaries appear to lag behind the runtime state.
The reporting pipeline exists, but it should be triggered more reliably.

### D. Overtrading / cost bleed risk
The logs show many short-duration trades and repeated re-entries.
That can destroy profitability even when gross PnL occasionally looks decent.

---

## 6) Improvements needed and exactly where to make them

## Priority 1 - Align the code with the actual experiment goal

### Goal
Decide whether this is:
1. an **intraday** experiment, or
2. a **multi-day / weekly positional** experiment

### Where to change
- **`scripts/app_config.py` / `config.py`**
  - trading time windows
  - holding duration rules
  - stop/target parameters
- **`scripts/paper_trade_engine_core.py`**
  - remove forced same-day exit if positional testing is intended
  - add max-hold-days logic
  - add overnight risk management

### Recommended improvement
If the goal is truly days/weeks:
- allow positions to remain open overnight
- add `max_hold_days`
- add separate positional stop-loss / trailing rules
- log overnight carry explicitly

---

## Priority 2 - Improve signal quality

### Current issue
The regime engine is simple and can produce too many weak entries.

### Where to change
- **`scripts/regime_classifier.py`**
- **`scripts/signal_engine.py`**

### Recommended improvement
Add stronger filters before entry:
- minimum trend strength threshold
- no-trade zone when bias is weak
- time-of-day filters
- avoid churn after regime flips
- optionally add VWAP / pullback confirmation

If moving toward a better experimental method, this is a strong next step.

---

## Priority 3 - Improve option selection logic

### Current issue
The system currently resolves the **nearest-expiry ATM option**.
That is fine for a basic experiment, but not enough for robust method testing.

### Where to change
- **`scripts/option_resolver.py`**

### Recommended improvement
Add support for:
- choosing expiry by DTE (days to expiry)
- selecting slightly OTM / ITM strikes
- configurable strike distance
- weekly vs monthly expiry experiments

---

## Priority 4 - Make reporting trustworthy and current

### Current issue
The runtime state and the daily summary files are not always in sync.

### Where to change
- **`scripts/analyze_trades.py`**
- optionally trigger it from **`scripts/evaluator_service.py`**

### Recommended improvement
- run reporting automatically after each exit or at end of every cycle
- add summary freshness timestamps
- include combined metrics that match the latest PnL state

This is essential because the whole purpose of the repo is experimental evaluation.

---

## Priority 5 - Add research-grade metrics

### Goal
The output should clearly answer whether the method is worth continuing.

### Where to change
- **`scripts/analyze_trades.py`**
- **`monitoring_web.py`**

### Recommended metrics
Add:
- expectancy per trade
- profit factor
- max drawdown
- average win / average loss
- win rate by regime
- win rate by time of day
- net PnL after realistic costs
- streak analysis

---

## Priority 6 - Improve realism of the paper experiment

### Where to change
- **`scripts/paper_trade_engine_core.py`**
- **`scripts/utils.py`**
- **`scripts/analyze_trades.py`**

### Recommended improvement
Use more realistic assumptions:
- slippage model
- brokerage + exchange charges
- liquidity filter
- no-entry when LTP is missing or spread is too wide

---

## 7) Suggested next implementation order

### Option A - Continue as an intraday experiment
If the immediate aim is only to test whether the current intraday method has edge:

1. tighten entry filters
2. reduce overtrading
3. improve reporting
4. compare SELL vs BUY side performance
5. run for more sessions and review metrics

### Option B - Convert it to the intended days/weeks experiment
If the real aim is positional profitability over days/weeks:

1. allow overnight holds
2. add max-hold-days and expiry-selection controls
3. improve option selection and risk management
4. add positional reporting metrics
5. then re-run the experiment over multiple weeks

---

## 8) Recommended next session starting point

When resuming work, start here:

### Immediate focus
**Decide and lock the experiment definition:**
- intraday profitability test, or
- multi-day/weekly profitability test

### Best practical next coding step
If no decision is made yet, the safest next improvement is:

> **Improve reporting and signal quality first, without changing the whole architecture.**

That means working mainly in:
- `scripts/regime_classifier.py`
- `scripts/signal_engine.py`
- `scripts/analyze_trades.py`
- `monitoring_web.py`

---

## 9) One-line summary

**The current repo is a working intraday paper-trading experiment harness for NIFTY options, but it still needs signal refinement, fresher reporting, and positional-hold support if the true goal is to test profitability over days and weeks.**
