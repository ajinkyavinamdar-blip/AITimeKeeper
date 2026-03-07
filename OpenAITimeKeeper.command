#!/bin/bash
# AI TimeKeeper Launcher for macOS

# Get the directory where the script is located
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "Stopping any existing AI TimeKeeper processes..."
# Kill any existing python processes running main.py
ps aux | grep "[p]ython3 main.py" | awk '{print $2}' | xargs kill -9 2>/dev/null

# Kill anything on port 5001
lsof -t -i :5001 | xargs kill -9 2>/dev/null

echo "Starting AI TimeKeeper..."
# Start the app in a new terminal window or just here? 
# Using python3 main.py directly
python3 main.py &

echo "AI TimeKeeper is starting in the background."
echo "You can access the dashboard at http://127.0.0.1:5001"
echo "This window will close in 5 seconds."
sleep 5
exit 0
