"""
uploader.py — TimePulse: POSTs activity batches to /api/ingest.
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
import logging
import requests

log = logging.getLogger("agent.uploader")

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

    # First try to drain any buffered offline queue from previous failures
    _drain_queue(cfg)

    # Retry loop with exponential backoff
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(
                f"{server_url}/api/ingest",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"logs": logs, "agent_version": cfg.get("agent_version", "")},
                timeout=TIMEOUT,
            )
            if resp.status_code == 401:
                log.error("Auth failed — check your API token in ~/.aitimekeeper/config.json")
                return False
            resp.raise_for_status()
            result = resp.json()
            accepted = result.get('accepted', '?')
            if attempt > 1:
                log.info(f"Uploaded {accepted} rows (succeeded on attempt {attempt})")
            else:
                log.info(f"Uploaded {accepted} rows")
            return True
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                wait = 2 ** attempt  # 2s, 4s
                log.warning(f"Attempt {attempt}/{MAX_RETRIES} failed ({e}), retrying in {wait}s...")
                time.sleep(wait)

    # All retries exhausted — queue offline for later
    log.warning(f"All {MAX_RETRIES} attempts failed ({last_err}), "
                f"queuing {len(logs)} rows offline for later upload")
    _append_to_queue(logs)
    return False


def get_queue_size() -> int:
    """Return the number of entries waiting in the offline queue."""
    return len(_load_queue())


def _append_to_queue(logs: list):
    """Persist failed logs to the offline queue file (capped)."""
    existing = _load_queue()
    existing.extend(logs)
    # Cap queue size — keep newest rows
    if len(existing) > MAX_QUEUE_SIZE:
        dropped = len(existing) - MAX_QUEUE_SIZE
        existing = existing[-MAX_QUEUE_SIZE:]
        log.warning(f"Offline queue capped: dropped {dropped} oldest rows")
    os.makedirs(os.path.dirname(OFFLINE_QUEUE_FILE), exist_ok=True)
    with open(OFFLINE_QUEUE_FILE, "w") as f:
        json.dump(existing, f)
    log.info(f"Offline queue now has {len(existing)} rows")


def _load_queue() -> list:
    if not os.path.exists(OFFLINE_QUEUE_FILE):
        return []
    try:
        with open(OFFLINE_QUEUE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []


def _drain_queue(cfg: dict):
    """Attempt to upload queued rows from previous failures. Clears file on success."""
    queued = _load_queue()
    if not queued:
        return
    log.info(f"Found {len(queued)} rows in offline queue — uploading now...")
    server_url = cfg["server_url"].rstrip("/")
    token = cfg["api_token"]
    try:
        resp = requests.post(
            f"{server_url}/api/ingest",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"logs": queued, "agent_version": cfg.get("agent_version", "")},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        result = resp.json()
        accepted = result.get('accepted', '?')
        # Clear queue on success
        with open(OFFLINE_QUEUE_FILE, "w") as f:
            json.dump([], f)
        log.info(f"Offline queue flushed — {accepted} previously-queued rows uploaded")
    except Exception as e:
        log.warning(f"Could not drain offline queue yet: {e}")
