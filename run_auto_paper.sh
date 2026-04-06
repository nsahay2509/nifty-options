#!/usr/bin/env bash
set -euo pipefail
cd /home/ubuntu/nifty
exec python3 scripts/auto_paper_runtime.py
