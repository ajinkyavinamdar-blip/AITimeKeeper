"""
uploader.py — POSTs activity batches to /api/ingest.
Stores failed batches in ~/.aitimekeeper/offline_queue.json for retry.

Resilience features:
- 3 retries with exponential backoff per upload attempt
- 30s timeout (handles Render free-tier cold starts)
- Offline queue for persistent retry across restarts
- Queue cap (10,000 rows) to prevent unbounded disk growth
"""
import json
import os
import time
import requests

OFFLINE_QUEUE_FILE = os.path.join(os.path.expanduser("~"), ".aitimekeeper", "offline_queue.json")
TIMEOUT = 30          # seconds — Render cold start can take 20-30s
MAX_RETRIES = 3       # attempts per upload
MAX_QUEUE_SIZE = 10000  # max rows in offline queue


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

    # Retry loop with exponential backoff
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
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
            accepted = result.get('accepted', '?')
            if attempt > 1:
                print(f"[uploader] Uploaded {accepted} rows (succeeded on attempt {attempt})")
            else:
                print(f"[uploader] Uploaded {accepted} rows")
            return True
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                wait = 2 ** attempt  # 2s, 4s
                print(f"[uploader] Attempt {attempt}/{MAX_RETRIES} failed ({e}), retrying in {wait}s...")
                time.sleep(wait)

    # All retries exhausted — queue offline
    print(f"[uploader] All {MAX_RETRIES} attempts failed ({last_err}), queuing {len(logs)} rows offline")
    _append_to_queue(logs)
    return False


def _append_to_queue(logs: list):
    """Persist failed logs to the offline queue file (capped)."""
    existing = _load_queue()
    existing.extend(logs)
    # Cap queue size — keep newest rows
    if len(existing) > MAX_QUEUE_SIZE:
        dropped = len(existing) - MAX_QUEUE_SIZE
        existing = existing[-MAX_QUEUE_SIZE:]
        print(f"[uploader] Offline queue capped: dropped {dropped} oldest rows")
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
