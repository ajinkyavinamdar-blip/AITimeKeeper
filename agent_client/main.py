"""
main.py — TimePulse Desktop Agent (lightweight, cloud-connected)

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

AGENT_VERSION = '1.5.0'

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
            "TimePulse must continuously track user activity"
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
    """Kill any other TimePulse/AITimeKeeper processes to prevent duplicates."""
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
            if 'timepulse' in name or 'timepulse' in cmdline or 'aitimekeeper' in name or 'aitimekeeper' in cmdline:
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
    # How long a user must be inactive before considered idle (seconds)
    IDLE_THRESHOLD = 180  # 3 minutes

    # If idle detection claims "idle" continuously for this many seconds,
    # something is wrong (pynput stopped working) — auto-disable.
    STALENESS_LIMIT = 300  # 5 minutes

    def __init__(self, threshold_seconds=None):
        self.last_activity = time.time()
        self.threshold = threshold_seconds or self.IDLE_THRESHOLD
        self._disabled = False
        self._idle_since = None  # timestamp when is_idle() first returned True

    @staticmethod
    def _is_accessibility_trusted():
        """Check macOS Accessibility permission via AXIsProcessTrusted()."""
        if platform.system() != "Darwin":
            return True  # non-macOS: assume OK
        try:
            import ctypes
            import ctypes.util
            lib = ctypes.cdll.LoadLibrary(
                '/System/Library/Frameworks/ApplicationServices.framework'
                '/ApplicationServices'
            )
            lib.AXIsProcessTrusted.restype = ctypes.c_bool
            return lib.AXIsProcessTrusted()
        except Exception:
            return True  # can't check → assume OK, pynput will fail visibly

    def start(self):
        # Check Accessibility FIRST — if not trusted, pynput WILL fail
        if not self._is_accessibility_trusted():
            log.warning("Accessibility permission NOT granted. "
                        "Disabling idle detection — tracking will run continuously. "
                        "Grant permission in System Settings > Privacy & Security > "
                        "Accessibility to enable idle detection.")
            self._disabled = True
            return

        try:
            self._ml = mouse.Listener(on_move=self._touch, on_click=self._touch, on_scroll=self._touch)
            self._kl = keyboard.Listener(on_press=self._touch)
            self._ml.start()
            self._kl.start()
            log.info("IdleFilter started — Accessibility permission OK")
        except Exception as e:
            log.warning(f"pynput listeners failed: {e}. Disabling idle detection.")
            self._disabled = True

    def _touch(self, *_):
        self.last_activity = time.time()

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

        idle = (time.time() - self.last_activity) > self.threshold

        if idle:
            # Track how long we've been continuously "idle"
            if self._idle_since is None:
                self._idle_since = time.time()
            elif (time.time() - self._idle_since) > self.STALENESS_LIMIT:
                # Idle for 5+ minutes straight — pynput likely stopped receiving
                # events (macOS killed listeners, or Accessibility was revoked).
                # Disable to prevent permanent tracking stoppage.
                log.warning(f"IdleFilter reported idle for >{self.STALENESS_LIMIT}s straight. "
                            "pynput likely stopped working. Disabling idle detection — "
                            "tracking will run continuously.")
                self._disabled = True
                return False
        else:
            self._idle_since = None  # reset — user is active

        return idle


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

        # Check server pause state BEFORE starting to track
        self._check_initial_pause_state()

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

        log.info(f"Tracking started for {self.cfg['user_email']}"
                 f"{' (PAUSED via server)' if self.paused else ''}")
        self._track_loop()

    def _check_initial_pause_state(self):
        """On startup, check if the server has us paused (e.g. user paused from web UI
        before a reboot). This prevents tracking in the gap before the first control poll."""
        import requests as _req
        try:
            server_url = self.cfg.get('server_url', '').rstrip('/')
            token = self.cfg.get('api_token', '')
            resp = _req.get(
                f"{server_url}/api/agent/poll",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get('paused'):
                    self.paused = True
                    log.info("Server indicates PAUSED state on startup")
        except Exception as e:
            log.debug(f"Could not check initial pause state: {e}")

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
        first_run = True
        while self.running:
            try:
                # First upload after 10s (enough to collect some data), then every 30s
                time.sleep(10 if first_run else self.UPLOAD_INTERVAL)
                first_run = False
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
                        log.info("Server says PAUSED — pausing tracking")
                        self.pause()
                    elif not server_paused and self.paused:
                        log.info("Server says RESUME — resuming tracking")
                        self.resume()
                elif resp.status_code == 404:
                    # Endpoint doesn't exist on this server — stop polling
                    log.info("Control poll endpoint not available (404), disabling server pause sync")
                    return
                elif resp.status_code == 401:
                    if _consecutive_poll_errors == 0:
                        log.warning("Control poll: 401 Unauthorized — check API token")
                    _consecutive_poll_errors += 1
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
    """Draw a waveform/pulse icon with cyan→blue→purple gradient for TimePulse."""
    from PIL import Image, ImageDraw
    SIZE = 64
    img = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Dark rounded-square background
    d.rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=14, fill=(15, 23, 42, 255))

    # Waveform matching logo: flat → peak up → drop → circle → deep V → recover → flat
    pad = 8
    w = SIZE - 2 * pad
    cy = SIZE // 2

    points = [
        (pad, cy + 2),                        # start flat
        (pad + w * 0.14, cy + 2),              # end flat
        (pad + w * 0.22, cy - 4),              # gentle rise
        (pad + w * 0.30, cy - w * 0.42),       # sharp peak UP
        (pad + w * 0.40, cy + w * 0.30),       # drop below center
        (pad + w * 0.47, cy),                  # cross center (circle here)
        (pad + w * 0.55, cy + 2),              # slight dip
        (pad + w * 0.62, cy + w * 0.35),       # deep V down
        (pad + w * 0.72, cy - w * 0.22),       # sharp recovery up
        (pad + w * 0.80, cy + 2),              # settle back
        (SIZE - pad, cy + 2),                  # end flat
    ]

    # Gradient segments (cyan → blue → purple)
    colors = [
        (6, 182, 212),    # cyan
        (6, 182, 212),    # cyan
        (6, 182, 212),    # cyan
        (20, 156, 230),   # cyan-blue
        (40, 140, 240),   # blue
        (59, 130, 246),   # blue
        (80, 110, 240),   # blue-purple
        (120, 96, 246),   # purple
        (139, 92, 246),   # purple
        (139, 92, 246),   # purple
    ]
    for i in range(len(points) - 1):
        d.line([points[i], points[i + 1]], fill=colors[i], width=3)

    # Circle/dot at the center crossing point
    cx_dot = int(pad + w * 0.47)
    cy_dot = cy
    d.ellipse([cx_dot - 4, cy_dot - 4, cx_dot + 4, cy_dot + 4],
              fill=(59, 130, 246, 80))
    d.ellipse([cx_dot - 2, cy_dot - 2, cx_dot + 2, cy_dot + 2],
              fill=(59, 130, 246, 220))

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
        version    = AGENT_VERSION

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
            pystray.MenuItem('Quit TimePulse', on_quit),
        )
        icon = pystray.Icon('TimePulse', img, 'TimePulse', menu)
        return icon
    except Exception as e:
        log.error(f"Could not create tray icon: {e}")
        return None


# ── Startup UI helpers ────────────────────────────────────────────────────────

def _show_notification(title, message):
    """Show a macOS notification (non-blocking)."""
    if platform.system() != "Darwin":
        return
    try:
        import subprocess
        script = f'display notification "{message}" with title "{title}"'
        subprocess.Popen(['osascript', '-e', script],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def _show_error_dialog(title, message):
    """Show a blocking error dialog on macOS."""
    if platform.system() == "Darwin":
        try:
            import subprocess
            script = (
                f'display dialog "{message}" '
                f'with title "{title}" '
                f'buttons {{"OK"}} default button "OK" '
                f'with icon stop'
            )
            subprocess.run(['osascript', '-e', script], timeout=60)
        except Exception:
            pass
    log.error(f"{title}: {message}")


def _run_status_window(loop, cfg):
    """Show a recurring AppleScript dialog as a simple control panel.
    This is the fallback when pystray is unavailable."""
    if platform.system() != "Darwin":
        # On non-Mac, just block the main thread
        try:
            while loop.running:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        return

    import subprocess
    user_email = cfg.get('user_email', 'Unknown')

    while loop.running:
        # Build status text
        status = "Paused" if loop.paused else "Tracking"
        uploaded = loop._upload_count
        tracked = loop._track_count
        failures = loop._consecutive_upload_failures

        if loop._last_successful_upload:
            ago = int(time.time() - loop._last_successful_upload)
            upload_info = f"{ago}s ago" if ago < 60 else f"{ago // 60}m ago"
        else:
            upload_info = "waiting..."

        msg = (
            f"Status: {status}\\n"
            f"User: {user_email}\\n"
            f"Version: {AGENT_VERSION}\\n\\n"
            f"Tracked: {tracked} entries\\n"
            f"Uploaded: {uploaded} entries\\n"
            f"Last upload: {upload_info}\\n"
            f"Failures: {failures}"
        )

        action = "Pause Tracking" if not loop.paused else "Resume Tracking"

        script = (
            f'display dialog "{msg}" '
            f'with title "TimePulse" '
            f'buttons {{"Quit", "{action}", "Hide"}} '
            f'default button "Hide" '
            f'with icon note '
            f'giving up after 30'
        )
        try:
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True, text=True, timeout=35
            )
            output = result.stdout.strip()

            if "Quit" in output:
                log.info("User clicked Quit in status window")
                loop.flush_and_stop()
                return
            elif action in output:
                if loop.paused:
                    loop.resume()
                    log.info("Resumed via status window")
                else:
                    loop.pause()
                    log.info("Paused via status window")
            elif "Hide" in output or "gave up" in output:
                # User clicked Hide or dialog timed out — wait before showing again
                # Wait 60s, but check every second so we can exit promptly
                for _ in range(60):
                    if not loop.running:
                        return
                    time.sleep(1)
            elif result.returncode != 0:
                # Dialog was cancelled (e.g., Cmd+Q) — wait and retry
                for _ in range(60):
                    if not loop.running:
                        return
                    time.sleep(1)
        except subprocess.TimeoutExpired:
            continue
        except Exception as e:
            log.error(f"Status window error: {e}")
            time.sleep(10)


# ── Entry Point ───────────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info(f"TimePulse agent starting (v{AGENT_VERSION})")
    log.info(f"Platform: {platform.system()} {platform.release()}")
    log.info(f"Python: {sys.version}")
    log.info(f"PID: {os.getpid()}")
    log.info("=" * 60)

    # Show launch notification so user knows the app is starting
    _show_notification("TimePulse", f"Starting v{AGENT_VERSION}...")

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
            _show_error_dialog("TimePulse — Setup Failed",
                               f"Could not complete setup: {e}\\n\\nRestart the app to try again.")
            sys.exit(1)

    # Inject version so uploader can report it in ingest payload
    cfg['agent_version'] = AGENT_VERSION
    loop = AgentLoop(cfg)

    tray_icon = _build_tray_icon(loop)
    if tray_icon:
        _show_notification("TimePulse",
                           f"Tracking active for {cfg.get('user_email', 'unknown')}. Look for the icon in your menu bar.")
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
        # No tray icon — show a status window with controls instead
        log.warning("Could not create tray icon — using status window")
        _show_notification("TimePulse",
                           f"Tracking active for {cfg.get('user_email', 'unknown')}.")
        tracking_thread = threading.Thread(target=loop.start, daemon=True)
        tracking_thread.start()
        try:
            _run_status_window(loop, cfg)
        except KeyboardInterrupt:
            pass
        finally:
            loop.flush_and_stop()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.critical(f"FATAL: {e}\n{traceback.format_exc()}")
        _show_error_dialog(
            "TimePulse — Crash",
            f"The app encountered an error and needs to close:\\n\\n{e}\\n\\nCheck ~/.aitimekeeper/agent.log for details."
        )
        sys.exit(1)
