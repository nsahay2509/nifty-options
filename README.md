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
- [docs/PROGRESS_LOG.md](/home/ubuntu/nifty/docs/PROGRESS_LOG.md): dated progress, rationale, and result log
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

This rebuild has now moved beyond the minimal starting point and is running as a working evaluation stack.

### Progress Snapshot — 2026-04-06

- ✅ market-calendar and runtime lifecycle foundation is in place
- ✅ websocket-driven evaluation runtime is working during valid NSE trading sessions
- ✅ monitoring UI at `https://nifty.nsrk.in/` is live and now mode-neutral
- ✅ automatic holiday/weekend-aware supervisor is enabled via `nifty-auto-paper.service`
- ✅ monitor UI can stay running independently via `nifty-monitor.service`
- ✅ manual operational commands are documented in [`commands.md`](/home/ubuntu/nifty/commands.md)

### Immediate Next Step

Add **trade timing controls** so the system can keep running through the session, while allowing new entries only inside a configured intraday entry window.

The old system is preserved in [archive](/home/ubuntu/nifty/archive), but it should be treated as reference material only, not as the template for the new design.