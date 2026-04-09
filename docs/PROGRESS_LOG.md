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

---

## 2026-04-09 — Live stale-resolution, index feed diagnosis, and immediate-entry recovery

### Context

During PAPER runtime monitoring on `2026-04-09`, the dashboard repeatedly showed:
- `System: STALE`
- `Session status: System stale`

even while `nifty-auto-paper.service` remained active.

At the same time, config was intentionally set to immediate confirmation:
- `entry_confirmations_required = 1`
- `exit_confirmations_required = 1`

The expected behavior was immediate trade entry on the next valid 1-minute signal.

### Root causes found

1. Freshness signal gap:
- the monitor considered runtime fresh only when specific event logs appeared
- during quiet periods, freshness could expire even though runtime loop was alive

2. Index feed starvation:
- futures/options ticks were streaming, but index ticks were absent for long periods
- no index candles meant no `PAPER_EVAL_RESULT`, therefore no entries regardless of `1/1` confirmation

3. Dhan mode compatibility issue:
- live websocket probing showed index `sid=13` did not reliably arrive in FULL mode (`RequestCode=21`)
- the same index stream appeared in QUOTE/TICKER mode (`RequestCode=17/15`)

### Changes made

#### 1) Monitoring freshness hardening
- updated `scripts/run_paper_live_eval.py` to emit periodic runtime heartbeats:
  - `PAPER_EVAL_HEARTBEAT | ticks=... decisions=...`
- updated `monitoring_web.py` heartbeat parser to treat `PAPER_EVAL_HEARTBEAT` as a freshness marker

#### 2) Feed watchdog reliability under continuous traffic
- updated `scripts/brokers/dhan_market_feed.py` so watchdog checks run on a periodic schedule even when `ws.recv()` never times out
- this enabled index-stall recovery actions (`resubscribe`/`reconnect`) while futures/options were still flowing

#### 3) Index subscription mode routing fix
- updated `scripts/brokers/dhan_market_feed.py` to route index instruments to QUOTE mode when base mode is FULL
- non-index instruments continue in FULL mode
- practical effect: index stream reliability restored without downgrading full-depth coverage for derivatives

### Validation

Commands run:

```bash
python3 -m pytest tests/test_dhan_market_feed.py -q
python3 -m pytest tests/test_monitoring_web.py -q
```

Results:
- `tests/test_dhan_market_feed.py`: pass
- `tests/test_monitoring_web.py`: pass

Live runtime verification:
- services restarted and active: `nifty-auto-paper.service`, `nifty-monitor.service`
- index ticks resumed in stream health logs
- decision flow resumed with immediate confirmation behavior:
  - `PAPER_EVAL_RESULT`
  - `PAPER_EVAL_GATE ... action=enter`
  - `PAPER_EVAL_RECORDED` with new trade id

### Present stage

System is in operational PAPER mode with:
- active runtime services
- monitor freshness aligned to runtime heartbeat
- index feed auto-recovery and mode-safe subscription routing
- immediate confirmation gate (`1/1`) functioning as expected when tradeable state appears

### Note on environment

This repository is currently operated with direct `python3` commands (no local `venv` activation required in this workspace).
