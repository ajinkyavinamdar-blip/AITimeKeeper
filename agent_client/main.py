"""
main.py — AI TimeKeeper Desktop Agent (lightweight, cloud-connected)

Usage:
  python3 main.py                  # normal run
  python3 main.py --reset-config   # clear saved config and re-run setup

The agent records activity every 5 seconds locally and uploads in
batches to the central backend every 30 seconds.
"""
import os
import sys
import time
import datetime
import platform
import threading

import psutil

import config
import uploader


# ── Single Instance Guard ────────────────────────────────────────────────────

def _kill_old_instances():
    """Kill any other AITimeKeeper processes to prevent duplicates."""
    my_pid = os.getpid()
    my_ppid = os.getppid()
    killed = 0

    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            pid = proc.info['pid']
            if pid in (my_pid, my_ppid):
                continue
            name = (proc.info['name'] or '').lower()
            cmdline = ' '.join(proc.info['cmdline'] or []).lower()
            if 'aitimekeeper' in name or 'aitimekeeper' in cmdline:
                print(f"[agent] Killing old instance PID {pid}")
                proc.kill()
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    if killed:
        print(f"[agent] Cleaned up {killed} old instance(s)")

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
    WATCHDOG_INTERVAL = 60  # seconds between thread health checks

    def __init__(self, cfg):
        self.cfg = cfg
        self.buffer = []
        self.lock = threading.Lock()
        self.running = False
        self.paused = False   # controlled by tray menu OR server poll
        self.observer = _get_observer()
        self.idle_filter = IdleFilter()
        self._consecutive_upload_failures = 0
        self._last_successful_upload = None  # timestamp of last good upload
        self._threads = {}  # name → thread, for watchdog

    def pause(self):
        self.paused = True
        print("[agent] Tracking paused")

    def resume(self):
        self.paused = False
        print("[agent] Tracking resumed")

    def start(self):
        self.running = True
        self.idle_filter.start()

        self._start_thread('upload', self._upload_loop)
        self._start_thread('control', self._control_poll_loop)
        self._start_thread('watchdog', self._watchdog_loop)

        print(f"[agent] Tracking started for {self.cfg['user_email']}")
        self._track_loop()

    def _start_thread(self, name, target):
        """Start a named daemon thread, tracked for watchdog restarts."""
        t = threading.Thread(target=target, daemon=True, name=f'agent-{name}')
        t.start()
        self._threads[name] = (t, target)

    def _watchdog_loop(self):
        """Monitors critical threads and restarts any that have died."""
        while self.running:
            time.sleep(self.WATCHDOG_INTERVAL)
            for name, (thread, target) in list(self._threads.items()):
                if name == 'watchdog':
                    continue  # don't watch ourselves
                if not thread.is_alive():
                    print(f"[watchdog] Thread '{name}' died — restarting")
                    self._start_thread(name, target)

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
            try:
                time.sleep(self.UPLOAD_INTERVAL)
                if self.paused:
                    continue
                with self.lock:
                    batch = list(self.buffer)
                    self.buffer.clear()
                if batch:
                    ok = uploader.post_batch(self.cfg, batch)
                    if ok:
                        self._consecutive_upload_failures = 0
                        self._last_successful_upload = time.time()
                    else:
                        self._consecutive_upload_failures += 1
                        # Exponential backoff: wait extra time on repeated failures
                        # 30s, 60s, 120s, max 300s between attempts
                        backoff = min(self.UPLOAD_INTERVAL * (2 ** self._consecutive_upload_failures),
                                      300)
                        print(f"[agent] Upload failed ({self._consecutive_upload_failures}x), "
                              f"next retry in {backoff}s")
                        time.sleep(backoff - self.UPLOAD_INTERVAL)
            except Exception as e:
                # CRITICAL: catch ALL exceptions so the thread never dies
                print(f"[agent] Upload loop error (recovering): {e}")
                time.sleep(5)

    def _control_poll_loop(self):
        """Periodically asks the server whether this user's tracking is paused."""
        import requests
        while self.running:
            try:
                time.sleep(self.CONTROL_POLL_INTERVAL)
                server_url = self.cfg.get('server_url', '').rstrip('/')
                token = self.cfg.get('api_token', '')
                resp = requests.get(
                    f"{server_url}/api/agent/poll",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=15,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    server_paused = bool(data.get('paused', False))
                    if server_paused and not self.paused:
                        self.pause()
                    elif not server_paused and self.paused:
                        self.resume()
            except Exception as e:
                # CRITICAL: catch ALL exceptions so the thread never dies
                print(f"[agent] control poll error (recovering): {e}")
                time.sleep(5)

    def stop(self):
        self.running = False
        self.idle_filter.stop()


# ── System Tray ───────────────────────────────────────────────────────────────

def _make_icon_image():
    """Draw a lightning-bolt icon in app-brand indigo using PIL."""
    from PIL import Image, ImageDraw
    SIZE = 64
    img = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Indigo background circle
    d.ellipse([2, 2, SIZE - 2, SIZE - 2], fill=(79, 70, 229, 255))
    # White lightning bolt  (simplified polygon matching the app SVG)
    bolt = [
        (38, 8),   # top-right tip
        (24, 30),  # mid-left
        (34, 30),  # mid-right
        (26, 56),  # bottom tip
        (42, 34),  # lower-right
        (32, 34),  # lower-left
        (38, 8),   # close
    ]
    d.polygon(bolt, fill=(255, 255, 255, 255))
    return img


def _build_tray_icon(loop):
    """Creates and returns a pystray Icon (must be run on main thread on macOS)."""
    try:
        import pystray
        img = _make_icon_image()

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

        # Info items — displayed grayed-out, non-clickable
        user_email = loop.cfg.get('user_email', 'Unknown')
        version    = '1.4.0'

        def noop(icon, item):
            pass

        def upload_status(item):
            if loop._consecutive_upload_failures > 0:
                return f'⚠ Upload failing ({loop._consecutive_upload_failures}x)'
            elif loop._last_successful_upload:
                ago = int(time.time() - loop._last_successful_upload)
                if ago < 60:
                    return f'✓ Last upload: {ago}s ago'
                else:
                    return f'✓ Last upload: {ago // 60}m ago'
            else:
                return '⏳ Waiting for first upload...'

        menu = pystray.Menu(
            pystray.MenuItem(pause_label, on_pause_resume),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(upload_status, noop, enabled=False),
            pystray.MenuItem(f'User: {user_email}', noop, enabled=False),
            pystray.MenuItem(f'Version {version}',  noop, enabled=False),
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
    _kill_old_instances()

    if "--reset-config" in sys.argv:
        if os.path.exists(config.CONFIG_FILE):
            os.remove(config.CONFIG_FILE)
        print("Config cleared.")

    cfg = config.load()

    if not config.is_configured(cfg):
        cfg = config.first_run_setup()

    loop = AgentLoop(cfg)

    tray_icon = _build_tray_icon(loop)
    if tray_icon:
        # On macOS pystray MUST run on the main thread.
        # Move the tracking loop to a background thread instead.
        tracking_thread = threading.Thread(target=loop.start, daemon=True)
        tracking_thread.start()
        try:
            tray_icon.run()   # blocks on main thread — required by macOS
        except KeyboardInterrupt:
            pass
        finally:
            loop.stop()
    else:
        # No tray available — run tracking on main thread directly
        try:
            loop.start()
        except KeyboardInterrupt:
            print("\n[agent] Stopping...")
            loop.stop()


if __name__ == "__main__":
    main()
