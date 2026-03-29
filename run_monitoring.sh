#!/bin/bash

cd "$(dirname "$0")"

source venv/bin/activate

echo "Starting NIFTY Monitoring Web App..."
exec python -u monitoring_web.py
