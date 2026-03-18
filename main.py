from src.agent import TimeKeeperAgent
from src.web.app import start_server
from src.tray import SystemTrayApp
import threading
import time

def main():
    print("Initializing TimePulse...")
    
    # 1. Start Agent
    agent = TimeKeeperAgent()
    agent.start()
    
    # 2. Start Flask Server in a separate thread
    # Note: start_server runs app.run() which blocks, so we thread it.
    flask_thread = threading.Thread(target=start_server, args=(agent,), daemon=True)
    flask_thread.start()
    
    print("Flask server running at http://127.0.0.1:5001")
    
    # 3. Start System Tray (Main Thread)
    # Most GUI frameworks require running in the main thread.
    tray_app = SystemTrayApp(agent)
    tray_app.run()

if __name__ == "__main__":
    main()
