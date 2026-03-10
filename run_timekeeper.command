#!/bin/bash
# AI TimeKeeper Standalone Launcher

# Get the directory of this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "Stopping any existing AI TimeKeeper processes..."
# Kill any existing python processes running main.py
ps aux | grep "[p]ython3 main.py" | awk '{print $2}' | xargs kill -9 2>/dev/null

# Kill anything on port 5001
lsof -t -i :5001 | xargs kill -9 2>/dev/null

echo "Starting AI TimeKeeper..."
echo "You can close this window; the app will run in the background (check your system tray)."

# Run the app in the background
# We use python3 to run main.py which starts both the agent and the web server
nohup python3 main.py > /tmp/aitimekeeper.log 2>&1 &

echo "App started! Dashboard: http://127.0.0.1:5001"
# Optionally open the dashboard immediately
# open http://127.0.0.1:5001
