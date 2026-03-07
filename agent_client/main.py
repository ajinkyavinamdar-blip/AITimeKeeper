"""
main.py — AI TimeKeeper Desktop Agent (lightweight, cloud-connected)

Usage:
  python3 main.py                  # normal run
  python3 main.py --reset-config   # clear saved config and re-run setup

The agent records activity every 5 seconds locally and uploads in
batches to the central backend every 30 seconds.
"""
import sys
import time
import datetime
import platform
import threading

import config
import uploader

# ── Platform Observer ─────────────────────────────────────────────────────────

def _get_observer():
    os_type = platform.system()
    if os_type == "Darwin":
        from observer_mac import MacObserver
        return MacObserver()
    elif os_type == "Windows":
        from observer_win import WindowsObserver
        return WindowsObserver()
    else:
        print(f"Unsupported OS: {os_type}")
        return None


# ── Idle Filter ───────────────────────────────────────────────────────────────

from pynput import mouse, keyboard

class IdleFilter:
    def __init__(self, threshold_seconds=180):
        self.last_activity = time.time()
        self.threshold = threshold_seconds
        self._ml = mouse.Listener(on_move=self._touch, on_click=self._touch, on_scroll=self._touch)
        self._kl = keyboard.Listener(on_press=self._touch)

    def _touch(self, *_):
        self.last_activity = time.time()

    def start(self):
        self._ml.start()
        self._kl.start()

    def stop(self):
        self._ml.stop()
        self._kl.stop()

    def is_idle(self) -> bool:
        return (time.time() - self.last_activity) > self.threshold


# ── Main Loop ─────────────────────────────────────────────────────────────────

class AgentLoop:
    POLL_INTERVAL = 5      # seconds between activity checks
    UPLOAD_INTERVAL = 30   # seconds between batch uploads

    def __init__(self, cfg):
        self.cfg = cfg
        self.buffer = []
        self.lock = threading.Lock()
        self.running = False
        self.observer = _get_observer()
        self.idle_filter = IdleFilter()

    def start(self):
        self.running = True
        self.idle_filter.start()

        upload_thread = threading.Thread(target=self._upload_loop, daemon=True)
        upload_thread.start()

        print(f"[agent] Tracking started for {self.cfg['user_email']}")
        self._track_loop()

    def _track_loop(self):
        while self.running:
            try:
                if not self.idle_filter.is_idle() and self.observer:
                    activity = self.observer.get_current_activity()
                    entry = {
                        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "app_name": activity.app_name,
                        "window_title": activity.window_title,
                        "url_or_filename": activity.url_or_filename,
                        "chrome_profile": getattr(activity, "chrome_profile", ""),
                        "client": "Unassigned",
                        "duration": float(self.POLL_INTERVAL),
                        "category_id": None,
                    }
                    with self.lock:
                        self.buffer.append(entry)
            except Exception as e:
                print(f"[agent] Tracking error: {e}")
            time.sleep(self.POLL_INTERVAL)

    def _upload_loop(self):
        while self.running:
            time.sleep(self.UPLOAD_INTERVAL)
            with self.lock:
                batch = list(self.buffer)
                self.buffer.clear()
            if batch:
                uploader.post_batch(self.cfg, batch)

    def stop(self):
        self.running = False
        self.idle_filter.stop()


# ── Entry Point ───────────────────────────────────────────────────────────────

def main():
    if "--reset-config" in sys.argv:
        import os
        if os.path.exists(config.CONFIG_FILE):
            os.remove(config.CONFIG_FILE)
        print("Config cleared.")

    cfg = config.load()

    if not config.is_configured(cfg):
        cfg = config.first_run_setup()

    loop = AgentLoop(cfg)
    try:
        loop.start()
    except KeyboardInterrupt:
        print("\n[agent] Stopping...")
        loop.stop()


if __name__ == "__main__":
    main()
