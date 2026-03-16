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
    CONTROL_POLL_INTERVAL = 30  # seconds between checking server pause state

    def __init__(self, cfg):
        self.cfg = cfg
        self.buffer = []
        self.lock = threading.Lock()
        self.running = False
        self.paused = False   # controlled by tray menu OR server poll
        self.observer = _get_observer()
        self.idle_filter = IdleFilter()

    def pause(self):
        self.paused = True
        print("[agent] Tracking paused")

    def resume(self):
        self.paused = False
        print("[agent] Tracking resumed")

    def start(self):
        self.running = True
        self.idle_filter.start()

        upload_thread = threading.Thread(target=self._upload_loop, daemon=True)
        upload_thread.start()

        control_thread = threading.Thread(target=self._control_poll_loop, daemon=True)
        control_thread.start()

        print(f"[agent] Tracking started for {self.cfg['user_email']}")
        self._track_loop()

    def _track_loop(self):
        while self.running:
            try:
                if not self.paused and not self.idle_filter.is_idle() and self.observer:
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
            if self.paused:
                continue
            with self.lock:
                batch = list(self.buffer)
                self.buffer.clear()
            if batch:
                uploader.post_batch(self.cfg, batch)

    def _control_poll_loop(self):
        """Periodically asks the server whether this user's tracking is paused."""
        import requests
        while self.running:
            time.sleep(self.CONTROL_POLL_INTERVAL)
            try:
                server_url = self.cfg.get('server_url', '').rstrip('/')
                token = self.cfg.get('api_token', '')
                resp = requests.get(
                    f"{server_url}/api/agent/poll",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    server_paused = bool(data.get('paused', False))
                    if server_paused and not self.paused:
                        self.pause()
                    elif not server_paused and self.paused:
                        self.resume()
            except Exception as e:
                print(f"[agent] control poll error: {e}")

    def stop(self):
        self.running = False
        self.idle_filter.stop()


# ── System Tray ───────────────────────────────────────────────────────────────

def _build_tray_icon(loop):
    """Creates and returns a pystray Icon. Runs in its own thread."""
    try:
        import pystray
        from PIL import Image, ImageDraw

        # Draw a simple clock-face icon (16×16 fallback)
        img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse([4, 4, 60, 60], fill='#4F46E5')
        d.line([32, 32, 32, 14], fill='white', width=4)   # hour hand
        d.line([32, 32, 46, 38], fill='white', width=3)   # minute hand

        def on_pause_resume(icon, item):
            if loop.paused:
                loop.resume()
                # Sync to server
                import requests
                try:
                    s = loop.cfg.get('server_url', '').rstrip('/')
                    t = loop.cfg.get('api_token', '')
                    requests.post(f"{s}/api/control/resume",
                                  headers={"Authorization": f"Bearer {t}"}, timeout=5)
                except Exception:
                    pass
            else:
                loop.pause()
                import requests
                try:
                    s = loop.cfg.get('server_url', '').rstrip('/')
                    t = loop.cfg.get('api_token', '')
                    requests.post(f"{s}/api/control/pause",
                                  headers={"Authorization": f"Bearer {t}"}, timeout=5)
                except Exception:
                    pass
            icon.update_menu()

        def on_quit(icon, item):
            loop.stop()
            icon.stop()

        def pause_label(item):
            return 'Resume Tracking' if loop.paused else 'Pause Tracking'

        menu = pystray.Menu(
            pystray.MenuItem(pause_label, on_pause_resume),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('Quit AITimeKeeper', on_quit),
        )
        icon = pystray.Icon('AITimeKeeper', img, 'AI TimeKeeper', menu)
        return icon
    except Exception as e:
        print(f"[tray] Could not create tray icon: {e}")
        return None


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

    # Start tray icon in a background thread; tracking loop runs on main thread
    tray_icon = _build_tray_icon(loop)
    if tray_icon:
        tray_thread = threading.Thread(target=tray_icon.run, daemon=True)
        tray_thread.start()

    try:
        loop.start()   # blocks on _track_loop
    except KeyboardInterrupt:
        print("\n[agent] Stopping...")
        loop.stop()
        if tray_icon:
            tray_icon.stop()


if __name__ == "__main__":
    main()
