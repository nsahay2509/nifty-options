#!/bin/bash

BASE_DIR="/home/ubuntu/nifty"
SESSION="nifty_monitor"
RUN_SCRIPT="./run_monitoring.sh"
LOG_FILE="$BASE_DIR/logs/monitoring_restart.log"

mkdir -p "$BASE_DIR/logs"

cd "$BASE_DIR"

echo "---------------------------------" >> "$LOG_FILE"
echo "Restart triggered at $(date)" >> "$LOG_FILE"

tmux has-session -t $SESSION 2>/dev/null
if [ $? -eq 0 ]; then
    echo "Killing existing tmux session" >> "$LOG_FILE"
    tmux kill-session -t $SESSION
    sleep 2
fi

echo "Starting new tmux session" >> "$LOG_FILE"
tmux new-session -d -s $SESSION "$RUN_SCRIPT"

sleep 3

tmux has-session -t $SESSION 2>/dev/null
if [ $? -eq 0 ]; then
    echo "Restart successful" >> "$LOG_FILE"
else
    echo "Restart FAILED" >> "$LOG_FILE"
fi
