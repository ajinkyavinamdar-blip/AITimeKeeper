"""
uploader.py — POSTs activity batches to /api/ingest.
Stores failed batches in ~/.aitimekeeper/offline_queue.json for retry.
"""
import json
import os
import requests

OFFLINE_QUEUE_FILE = os.path.join(os.path.expanduser("~"), ".aitimekeeper", "offline_queue.json")
TIMEOUT = 10  # seconds


def post_batch(cfg: dict, logs: list) -> bool:
    """
    Ship a list of log-dicts to the server.
    Returns True on success, False on failure (writes to offline queue).
    """
    if not logs:
        return True

    server_url = cfg["server_url"].rstrip("/")
    token = cfg["api_token"]

    # First try to drain any buffered offline queue
    _drain_queue(cfg)

    try:
        resp = requests.post(
            f"{server_url}/api/ingest",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"logs": logs},
            timeout=TIMEOUT,
        )
        if resp.status_code == 401:
            print("[uploader] Auth failed — check your API token in ~/.aitimekeeper/config.json")
            return False
        resp.raise_for_status()
        result = resp.json()
        print(f"[uploader] Uploaded {result.get('accepted', '?')} rows")
        return True
    except Exception as e:
        print(f"[uploader] Upload failed ({e}), queuing offline")
        _append_to_queue(logs)
        return False


def _append_to_queue(logs: list):
    """Persist failed logs to the offline queue file."""
    existing = _load_queue()
    existing.extend(logs)
    os.makedirs(os.path.dirname(OFFLINE_QUEUE_FILE), exist_ok=True)
    with open(OFFLINE_QUEUE_FILE, "w") as f:
        json.dump(existing, f)


def _load_queue() -> list:
    if not os.path.exists(OFFLINE_QUEUE_FILE):
        return []
    try:
        with open(OFFLINE_QUEUE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []


def _drain_queue(cfg: dict):
    """Attempt to upload queued rows. Clears file on success."""
    queued = _load_queue()
    if not queued:
        return
    print(f"[uploader] Retrying {len(queued)} offline-queued rows...")
    server_url = cfg["server_url"].rstrip("/")
    token = cfg["api_token"]
    try:
        resp = requests.post(
            f"{server_url}/api/ingest",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"logs": queued},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        # Clear queue on success
        with open(OFFLINE_QUEUE_FILE, "w") as f:
            json.dump([], f)
        print(f"[uploader] Offline queue flushed ({len(queued)} rows)")
    except Exception as e:
        print(f"[uploader] Could not drain offline queue: {e}")
