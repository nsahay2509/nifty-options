

#!/bin/bash

cd "$(dirname "$0")"

source venv/bin/activate

if [ -z "${DHAN_ENV_FILE:-}" ] && [ -f "/home/ubuntu/nseo/.env" ]; then
    export DHAN_ENV_FILE="/home/ubuntu/nseo/.env"
fi

echo "Starting NIFTY Evaluator with auto-restart..."

while true
do
    echo "--------------------------------------------"
    echo "Restart time: $(date)"
    python -u nifty_evaluator.py
    echo "Process crashed. Restarting in 5 seconds..."
    sleep 5
done
