# Progress Log

This file is the running reference for **what changed, why it changed, what result we observed, and what to check next**.

Use it as the first place to look before making follow-up changes.

---

## 2026-04-07 — Reporting, MTM reset, enriched trade records, and confirmation gating

### Context

During review of the paper-trading outputs, two issues became clear:

1. `trade_records_YYYY-MM-DD.csv` and `trade_summary_YYYY-MM-DD.json` were not showing the true realised trade P&L.
2. `live_paper_mtm.json` was carrying prior-session realised P&L into the next day.
3. The runtime was flipping too quickly between states, producing too many trades for an early experimental setup.

### Changes made

#### 1) Fixed realised P&L reporting path
- updated `scripts/trade_recorder.py` so closed trades can be finalized with actual `gross_pnl`, `net_pnl`, and exit metadata
- updated `scripts/run_paper_live_eval.py` so close events from the MTM tracker are written back into the session CSV and summary JSON

#### 2) Fixed daily MTM reset behavior
- updated `scripts/paper_mtm.py` so `realised_pnl_today` and close counters reset by `session_date`
- confirmed that the previous value had included `2026-04-06` realised P&L in the `2026-04-07` snapshot

#### 3) Enriched the trade CSV schema
Added fields such as:
- `status`
- `opened_at`
- `closed_at`
- `holding_minutes`
- `trade_bias`
- `entry_reason`
- `underlying_entry_price`
- `underlying_exit_price`
- `entry_credit`
- `entry_debit`
- `exit_close_value`
- `realised_pnl`
- `unrealised_pnl`
- `option_types`
- `leg_count`
- `leg_symbols`
- `legs_json`

This was done so later analysis has the actual lifecycle and structure context for each trade.

#### 4) Added configurable confirmation gating
In `scripts/config.py`:
- `entry_confirmations_required = 3`
- `exit_confirmations_required = 3`

In `scripts/run_paper_live_eval.py`:
- entries now require the same tradeable state to appear in **3 consecutive 1-minute assessments**
- exits now require **3 consecutive non-matching assessments** before the current trade is closed

### Why these changes were made

- to make the paper-trading results auditable and interpretable
- to preserve rationale for later strategy review
- to reduce state-churn overtrading during the experimental phase
- to improve confidence that the next day's CSV reflects more meaningful trades

### Result observed

- `trade_summary_2026-04-07.json` now reflects real realised P&L instead of all-zero aggregation
- `trade_records_2026-04-07.csv` now contains enriched trade metadata
- next-session runtime behavior will be less noisy due to confirmation gating

### Verification

Command run:

```bash
cd /home/ubuntu/nifty && python3 -m pytest
```

Result:
- `49 passed in 0.17s`

### Git checkpoint

- Commit: `db14ef4` — `Add confirmation gating and enrich paper trade records`
- Tag: `paper-confirmation-and-trade-records-2026-04-07`

### Next step

Run the system tomorrow with the present settings and inspect:
- trade count reduction
- state persistence behavior
- whether P&L quality improves
- whether the enriched CSV gives enough detail for useful post-trade analysis

---

## 2026-04-06 — Runtime foundation and monitoring milestone

### Summary

The rebuilt NIFTY stack reached a working operational baseline:
- state-driven runtime active
- monitoring UI live
- supervisor automation in place
- market-hours aware lifecycle enabled

### Focus after this point

Move from “runtime is working” to “trade behavior is high quality and explainable.”
