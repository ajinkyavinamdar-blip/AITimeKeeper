"""
config.py — reads/writes ~/.aitimekeeper/config.json
Schema:
  { "server_url": "https://...", "user_email": "...", "api_token": "..." }
"""
import json
import os

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".aitimekeeper")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")


def load():
    """Load config from disk. Returns a dict (empty if file missing)."""
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def save(cfg: dict):
    """Persist config to disk."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def is_configured(cfg: dict) -> bool:
    """Returns True if all required fields are present."""
    return all(cfg.get(k) for k in ("server_url", "user_email", "api_token"))


def first_run_setup():
    """Interactive first-run: asks user for details, fetches API token."""
    import requests

    print("\n=== AI TimeKeeper — First Run Setup ===")
    server_url = input("Server URL (e.g. https://your-app.onrender.com): ").strip().rstrip("/")
    user_email = input("Your work email: ").strip()

    print(f"\nFetching your API token from {server_url} ...")
    try:
        resp = requests.post(
            f"{server_url}/api/agent/provision",
            json={"email": user_email},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        api_token = data.get("token")
        if not api_token:
            raise ValueError("Server returned no token.")
        print("Token received. Saving config...")
    except Exception as e:
        print(f"Could not fetch token automatically: {e}")
        api_token = input("Paste your API token manually (from Dashboard → My Token): ").strip()

    cfg = {"server_url": server_url, "user_email": user_email, "api_token": api_token}
    save(cfg)
    print("Config saved. Starting tracking...\n")
    return cfg
