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
import json
import datetime
import platform
import threading
import logging
import traceback

import psutil

import config
import uploader

# ── Logging Setup ────────────────────────────────────────────────────────────

LOG_DIR = os.path.join(os.path.expanduser("~"), ".aitimekeeper")
LOG_FILE = os.path.join(LOG_DIR, "agent.log")
BUFFER_FILE = os.path.join(LOG_DIR, "pending_buffer.json")

os.makedirs(LOG_DIR, exist_ok=True)

# RotatingFileHandler to cap log size at 5MB
from logging.handlers import RotatingFileHandler
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.handlers.clear()

_log_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=2)
file_handler.setFormatter(_log_fmt)
root_logger.addHandler(file_handler)

# In bundled macOS .app (console=False), sys.stdout is None — skip console handler
if sys.stdout is not None:
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(_log_fmt)
    root_logger.addHandler(stdout_handler)

log = logging.getLogger("agent")


# ── Disable macOS App Nap ────────────────────────────────────────────────────

def _disable_app_nap():
    """Prevent macOS from suspending this process via App Nap.

    App Nap freezes background processes to save power, which kills
    our upload and tracking threads silently. This is the #1 cause of
    'logs stop flowing after 30 min'.
    """
    if platform.system() != "Darwin":
        return
    try:
        import objc
        from Foundation import NSProcessInfo
        info = NSProcessInfo.processInfo()
        # NSActivityUserInitiated | NSActivityIdleSystemSleepDisabled
        # This tells macOS: "I'm doing important user-initiated work,
        # don't suspend me or let the system idle-sleep"
        activity = info.beginActivityWithOptions_reason_(
            0x00FFFFFF,  # NSActivityUserInitiated (prevents App Nap + idle sleep)
            "AITimeKeeper must continuously track user activity"
        )
        log.info("macOS App Nap disabled successfully")
        return activity  # must keep reference alive
    except ImportError:
        log.warning("pyobjc not available — cannot disable App Nap. "
                     "Install with: pip install pyobjc-framework-Cocoa")
    except Exception as e:
        log.warning(f"Could not disable App Nap: {e}")
    return None


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
                log.info(f"Killing old instance PID {pid}")
                proc.kill()
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    if killed:
        log.info(f"Cleaned up {killed} old instance(s)")

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
        log.error(f"Unsupported OS: {os_type}")
        return None


# ── Idle Filter ───────────────────────────────────────────────────────────────

from pynput import mouse, keyboard

class IdleFilter:
    def __init__(self, threshold_seconds=180):
        self.last_activity = time.time()
        self.threshold = threshold_seconds
        self._disabled = False  # True if pynput can't listen (no Accessibility)
        self._ever_received_event = False
        self._started_at = None
        try:
            self._ml = mouse.Listener(on_move=self._touch, on_click=self._touch, on_scroll=self._touch)
            self._kl = keyboard.Listener(on_press=self._touch)
        except Exception as e:
            log.warning(f"pynput listeners could not be created: {e}")
            self._ml = None
            self._kl = None
            self._disabled = True

    def _touch(self, *_):
        self.last_activity = time.time()
        self._ever_received_event = True

    def start(self):
        if self._disabled:
            log.warning("IdleFilter disabled — pynput not available. "
                        "Tracking will run continuously without idle detection.")
            return
        self._started_at = time.time()
        try:
            self._ml.start()
            self._kl.start()
        except Exception as e:
            log.warning(f"pynput listeners failed to start: {e}")
            self._disabled = True

    def stop(self):
        if self._disabled:
            return
        try:
            self._ml.stop()
            self._kl.stop()
        except Exception:
            pass

    def is_idle(self) -> bool:
        if self._disabled:
            return False
        # Until pynput has proven it can receive events, assume user is active.
        # This prevents the false-idle bug when Accessibility permission is missing:
        # without it, _touch() is never called, last_activity freezes, and after
        # 3 minutes the agent would permanently think the user is idle.
        if not self._ever_received_event:
            # After 5 minutes with zero events, log a warning and permanently
            # disable idle detection (pynput clearly isn't working).
            if (self._started_at
                    and (time.time() - self._started_at) > 300):
                log.warning("IdleFilter has never received input events after 5 minutes. "
                            "pynput likely lacks Accessibility permission. "
                            "Disabling idle detection — tracking will run continuously. "
                            "Grant Accessibility permission in System Settings > "
                            "Privacy & Security > Accessibility to enable idle detection.")
                self._disabled = True
            return False  # assume active until proven otherwise
        return (time.time() - self.last_activity) > self.threshold


# ── Buffer Persistence ───────────────────────────────────────────────────────

def _save_buffer_to_disk(entries, overwrite=False):
    """Persist unsent entries to disk so they survive crashes.

    overwrite=True: replace file contents (used for periodic snapshots)
    overwrite=False: append to existing (used for shutdown saves)
    """
    if not entries:
        return
    try:
        if overwrite:
            data = entries
        else:
            data = _load_buffer_from_disk()
            data.extend(entries)
        # Cap at 50,000 entries (~7 hours of 5s polls) to prevent unbounded growth
        if len(data) > 50000:
            data = data[-50000:]
        with open(BUFFER_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        log.error(f"Failed to save buffer to disk: {e}")


def _load_buffer_from_disk():
    """Load any pending entries from a previous session/crash."""
    if not os.path.exists(BUFFER_FILE):
        return []
    try:
        with open(BUFFER_FILE, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _clear_buffer_on_disk():
    """Clear the on-disk buffer after successful upload."""
    try:
        with open(BUFFER_FILE, "w") as f:
            json.dump([], f)
    except Exception:
        pass


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
        self._track_count = 0  # entries tracked since start
        self._upload_count = 0  # entries uploaded since start

    def pause(self):
        self.paused = True
        log.info("Tracking paused")

    def resume(self):
        self.paused = False
        log.info("Tracking resumed")

    def start(self):
        self.running = True
        self.idle_filter.start()

        # Recover any unsent buffer from previous crash
        recovered = _load_buffer_from_disk()
        if recovered:
            log.info(f"Recovered {len(recovered)} unsent entries from previous session")
            with self.lock:
                self.buffer.extend(recovered)
            _clear_buffer_on_disk()

        self._start_thread('upload', self._upload_loop)
        self._start_thread('control', self._control_poll_loop)
        self._start_thread('watchdog', self._watchdog_loop)

        log.info(f"Tracking started for {self.cfg['user_email']}")
        self._track_loop()

    def _start_thread(self, name, target):
        """Start a named daemon thread, tracked for watchdog restarts."""
        t = threading.Thread(target=target, daemon=True, name=f'agent-{name}')
        t.start()
        self._threads[name] = (t, target)

    def _watchdog_loop(self):
        """Monitors critical threads, restarts dead ones, logs health stats."""
        while self.running:
            time.sleep(self.WATCHDOG_INTERVAL)
            try:
                for name, (thread, target) in list(self._threads.items()):
                    if name == 'watchdog':
                        continue
                    if not thread.is_alive():
                        log.warning(f"[watchdog] Thread '{name}' died — restarting")
                        self._start_thread(name, target)

                # Periodic health log (every 5 minutes)
                if int(time.time()) % 300 < self.WATCHDOG_INTERVAL:
                    with self.lock:
                        buf_size = len(self.buffer)
                    idle_str = "idle" if self.idle_filter.is_idle() else "active"
                    paused_str = "paused" if self.paused else "tracking"
                    idle_info = ""
                    if self.idle_filter._disabled:
                        idle_info = ", idle_filter=DISABLED"
                    elif not self.idle_filter._ever_received_event:
                        idle_info = ", idle_filter=NO_EVENTS"
                    log.info(f"[health] {paused_str}, {idle_str}, "
                             f"buffer={buf_size}, tracked={self._track_count}, "
                             f"uploaded={self._upload_count}, "
                             f"failures={self._consecutive_upload_failures}"
                             f"{idle_info}")
            except Exception as e:
                log.error(f"[watchdog] error: {e}")

    def _track_loop(self):
        save_counter = 0
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
                    self._track_count += 1

                    # Save buffer to disk every 6 entries (~30s) for crash recovery
                    save_counter += 1
                    if save_counter >= 6:
                        with self.lock:
                            snapshot = list(self.buffer)
                        _save_buffer_to_disk(snapshot, overwrite=True)
                        save_counter = 0
            except Exception as e:
                log.error(f"Tracking error: {e}")
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
                        self._upload_count += len(batch)
                        # Clear disk buffer — data is on the server now
                        _clear_buffer_on_disk()
                    else:
                        self._consecutive_upload_failures += 1
                        # On failure, uploader already saved to offline_queue.json
                        # Clear disk buffer to avoid duplication on restart
                        _clear_buffer_on_disk()
                        # Exponential backoff: wait extra time on repeated failures
                        backoff = min(self.UPLOAD_INTERVAL * (2 ** self._consecutive_upload_failures),
                                      300)
                        log.warning(f"Upload failed ({self._consecutive_upload_failures}x), "
                                    f"next retry in {backoff}s")
                        time.sleep(backoff - self.UPLOAD_INTERVAL)
            except Exception as e:
                # CRITICAL: catch ALL exceptions so the thread never dies
                log.error(f"Upload loop error (recovering): {e}\n{traceback.format_exc()}")
                time.sleep(5)

    def _control_poll_loop(self):
        """Periodically asks the server whether this user's tracking is paused."""
        import requests
        _consecutive_poll_errors = 0
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
                    try:
                        data = resp.json()
                    except ValueError:
                        # Server returned non-JSON (e.g. Render cold start HTML)
                        if _consecutive_poll_errors == 0:
                            log.debug("Control poll: server returned non-JSON, will retry")
                        _consecutive_poll_errors += 1
                        continue
                    _consecutive_poll_errors = 0
                    server_paused = bool(data.get('paused', False))
                    if server_paused and not self.paused:
                        self.pause()
                    elif not server_paused and self.paused:
                        self.resume()
                elif resp.status_code == 404:
                    # Endpoint doesn't exist on this server — stop polling
                    log.info("Control poll endpoint not available (404), disabling server pause sync")
                    return
            except Exception as e:
                _consecutive_poll_errors += 1
                # Only log first occurrence and then every 10th to avoid spam
                if _consecutive_poll_errors <= 1 or _consecutive_poll_errors % 10 == 0:
                    log.warning(f"control poll error ({_consecutive_poll_errors}x): {e}")
                time.sleep(5)

    def flush_and_stop(self):
        """Graceful shutdown: upload any remaining buffer, then stop."""
        log.info("Graceful shutdown — flushing remaining buffer...")
        self.running = False

        with self.lock:
            batch = list(self.buffer)
            self.buffer.clear()

        if batch:
            log.info(f"Flushing {len(batch)} entries on shutdown...")
            ok = uploader.post_batch(self.cfg, batch)
            if ok:
                log.info("Shutdown flush successful")
                _clear_buffer_on_disk()
            else:
                log.warning("Shutdown flush failed — saving to disk for next startup")
                _save_buffer_to_disk(batch)

        self.idle_filter.stop()
        log.info("Agent stopped cleanly")

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
            loop.flush_and_stop()
            icon.stop()

        def on_change_email(icon, item):
            new_cfg = config.change_email()
            if new_cfg:
                loop.cfg = new_cfg
                log.info(f"Email updated to {new_cfg['user_email']}")
                icon.update_menu()

        def pause_label(item):
            return 'Resume Tracking' if loop.paused else 'Pause Tracking'

        # Info items — displayed grayed-out, non-clickable
        version    = '1.4.4'

        def noop(icon, item):
            pass

        def user_label(item):
            return f"User: {loop.cfg.get('user_email', 'Unknown')}"

        def upload_status(item):
            queued = uploader.get_queue_size()
            if loop._consecutive_upload_failures > 0:
                base = f'⚠ Upload failing ({loop._consecutive_upload_failures}x)'
                return f'{base} · {queued} queued' if queued else base
            elif loop._last_successful_upload:
                ago = int(time.time() - loop._last_successful_upload)
                if ago < 60:
                    return f'✓ Last upload: {ago}s ago'
                else:
                    return f'✓ Last upload: {ago // 60}m ago'
            elif queued:
                return f'⏳ {queued} logs queued, waiting to upload...'
            else:
                return '⏳ Waiting for first upload...'

        menu = pystray.Menu(
            pystray.MenuItem(pause_label, on_pause_resume),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(upload_status, noop, enabled=False),
            pystray.MenuItem(user_label, noop, enabled=False),
            pystray.MenuItem('Change Email...', on_change_email),
            pystray.MenuItem(f'Version {version}',  noop, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('Quit AITimeKeeper', on_quit),
        )
        icon = pystray.Icon('AITimeKeeper', img, 'AI TimeKeeper', menu)
        return icon
    except Exception as e:
        log.error(f"Could not create tray icon: {e}")
        return None


# ── Entry Point ───────────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("AITimeKeeper agent starting (v1.4.4)")
    log.info(f"Platform: {platform.system()} {platform.release()}")
    log.info(f"Python: {sys.version}")
    log.info(f"PID: {os.getpid()}")
    log.info("=" * 60)

    _kill_old_instances()

    # Disable macOS App Nap (CRITICAL — prevents thread suspension)
    _app_nap_token = _disable_app_nap()

    if "--reset-config" in sys.argv:
        if os.path.exists(config.CONFIG_FILE):
            os.remove(config.CONFIG_FILE)
        log.info("Config cleared.")

    cfg = config.load()

    if not config.is_configured(cfg):
        try:
            cfg = config.first_run_setup()
        except (ValueError, Exception) as e:
            log.error(f"First-run setup failed: {e}")
            log.error("Agent cannot start without configuration. Exiting.")
            sys.exit(1)

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
            loop.flush_and_stop()
    else:
        # No tray available — run tracking on main thread directly
        try:
            loop.start()
        except KeyboardInterrupt:
            log.info("Stopping...")
            loop.flush_and_stop()


if __name__ == "__main__":
    main()
