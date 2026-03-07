from src.agent import TimeKeeperAgent
from src.web.app import start_server

if __name__ == "__main__":
    print("Starting AI TimeKeeper Debug Server...")
    agent = TimeKeeperAgent()
    agent.start()
    # This will block and keep the server running
    start_server(agent)
