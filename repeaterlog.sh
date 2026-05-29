#!/bin/bash

# Define file and session names
LOG_FILE="repeater.log"
SESSION_NAME="repeater_session"

# Clear any old log file from previous runs
#rm -f "$LOG_FILE"

# 1. Start the screen session in the background
screen -d -m -S "$SESSION_NAME" bash -c "ssh -o ConnectTimeout=5 -t charlesb@192.168.4.10 'journalctl -xeu pymc-repeater -f' | tee $LOG_FILE"

# 2. Get the unique PID of the screen session
SCREEN_PID=$(screen -ls | grep "$SESSION_NAME" | awk '{print $1}' | cut -d'.' -f1)

# 3. Set the trap to kill the screen session whenever this script exits
trap 'if [ -n "$SCREEN_PID" ]; then screen -S $SCREEN_PID -X quit; fi' EXIT

# 4. Verification Loop: Wait up to 10 seconds for the log file to receive data
echo "Connecting to remote server and verifying log stream..."
MAX_ATTEMPTS=10
ATTEMPT=0
VERIFIED=false

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    # Check if the file exists and has a size greater than 0 bytes
    if [ -s "$LOG_FILE" ]; then
        VERIFIED=true
        break
    fi
    sleep 1
    ((ATTEMPT++))
done

# 5. Handle verification outcome
if [ "$VERIFIED" = false ]; then
    echo "ERROR: Failed to connect or receive log data within 10 seconds."
    echo "Check your network connection, SSH keys, or remote service status."
    exit 1
fi

echo "Success: Log stream verified. Starting python tool..."

# 6. Start your Python script (blocks here until Python exits)
.venv/bin/python tools/live_log_compare.py --repeater-log "$LOG_FILE" --bridge-log meshbridge.log
