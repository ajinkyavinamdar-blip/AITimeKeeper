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


def _gui_prompt(title, prompt_text, default=""):
    import sys
    import platform
    if sys.stdin and sys.stdin.isatty():
        return input(f"{prompt_text} ").strip()
        
    if platform.system() == "Darwin":
        import subprocess
        script = f'''
        tell app "System Events"
            activate
            set dialogResult to display dialog "{prompt_text}" with title "{title}" default answer "{default}"
            return text returned of dialogResult
        end tell
        '''
        try:
            return subprocess.check_output(['osascript', '-e', script], text=True).strip()
        except Exception:
            return ""
    return ""


def first_run_setup():
    """Interactive first-run: asks user for details, fetches API token."""
    import requests

    print("\n=== AI TimeKeeper — First Run Setup ===")
    server_url = _gui_prompt("AI TimeKeeper Setup", "Server URL (e.g. https://your-app.onrender.com):", "https://aitimekeeper.onrender.com").rstrip("/")
    if not server_url:
        raise ValueError("Setup cancelled.")
        
    user_email = _gui_prompt("AI TimeKeeper Setup", "Your work email:")
    if not user_email:
        raise ValueError("Setup cancelled.")

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
        api_token = _gui_prompt("AI TimeKeeper Setup", "Could not fetch token. Paste your API token manually (from Dashboard -> My Token):")
        if not api_token:
            raise ValueError("Setup cancelled.")

    cfg = {"server_url": server_url, "user_email": user_email, "api_token": api_token}
    save(cfg)
    print("Config saved. Starting tracking...\n")
    return cfg
