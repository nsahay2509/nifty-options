#!/usr/bin/env bash
set -euo pipefail
cd /home/ubuntu/nifty
exec python3 monitoring_web.py
