


#!/bin/bash

BASE_DIR="/home/ubuntu/nifty"
SESSION="nifty_eval"
RUN_SCRIPT="./run_nifty.sh"
LOG_FILE="$BASE_DIR/logs/evaluator_restart.log"

mkdir -p "$BASE_DIR/logs"

cd "$BASE_DIR"

echo "---------------------------------" >> "$LOG_FILE"
echo "Restart triggered at $(date)" >> "$LOG_FILE"

# Kill existing session if running
tmux has-session -t $SESSION 2>/dev/null
if [ $? -eq 0 ]; then
    echo "Killing existing tmux session" >> "$LOG_FILE"
    tmux kill-session -t $SESSION
    sleep 2
fi

# Start new session
echo "Starting new tmux session" >> "$LOG_FILE"
tmux new-session -d -s $SESSION "$RUN_SCRIPT"

sleep 3

# Verify restart
tmux has-session -t $SESSION 2>/dev/null
if [ $? -eq 0 ]; then
    echo "Restart successful" >> "$LOG_FILE"
else
    echo "Restart FAILED" >> "$LOG_FILE"
fi