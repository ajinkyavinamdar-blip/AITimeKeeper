"""
config.py — reads/writes ~/.aitimekeeper/config.json
Schema:
  { "server_url": "https://...", "user_email": "...", "api_token": "..." }
"""
import json
import os
import sys
import platform
import logging

log = logging.getLogger("agent.config")

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".aitimekeeper")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")


def load():
    """Load config from disk. Returns a dict (empty if file missing)."""
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save(cfg: dict):
    """Persist config to disk."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def is_configured(cfg: dict) -> bool:
    """Returns True if all required fields are present."""
    return all(cfg.get(k) for k in ("server_url", "user_email", "api_token"))


def _gui_prompt(title, prompt_text, default=""):
    """Show a dialog to get text input from the user.

    macOS: uses osascript (works from background .app bundles).
    Windows: uses a tkinter dialog (bundled with Python, no extra deps).
    Fallback: stdin if available.
    """
    if sys.stdin and sys.stdin.isatty():
        return input(f"{prompt_text} [{default}]: ").strip() or default

    if platform.system() == "Darwin":
        import subprocess
        # Escape quotes and backslashes for AppleScript string literals
        _esc = lambda s: s.replace('\\', '\\\\').replace('"', '\\"')
        script = (
            f'display dialog "{_esc(prompt_text)}" '
            f'with title "{_esc(title)}" '
            f'default answer "{_esc(default)}" '
            f'with icon caution '
            f'buttons {{"Cancel", "OK"}} default button "OK"'
        )
        try:
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                log.warning(f"Dialog cancelled or failed: {result.stderr.strip()}")
                return ""
            output = result.stdout.strip()
            for part in output.split(", "):
                if part.startswith("text returned:"):
                    return part.split(":", 1)[1].strip()
            return ""
        except Exception as e:
            log.error(f"GUI prompt failed: {e}")
            return ""

    elif platform.system() == "Windows":
        return _win_input_dialog(title, prompt_text, default)

    return ""


def _win_input_dialog(title, prompt_text, default=""):
    """Show a text input dialog on Windows using tkinter."""
    try:
        import tkinter as tk
        from tkinter import simpledialog

        # Create a hidden root window
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)

        result = simpledialog.askstring(
            title, prompt_text,
            initialvalue=default,
            parent=root
        )
        root.destroy()
        return result.strip() if result else ""
    except Exception as e:
        log.error(f"Windows GUI prompt failed: {e}")
        # Last resort: try ctypes MessageBox + VBScript InputBox
        return _win_vbs_input(title, prompt_text, default)


def _win_vbs_input(title, prompt_text, default=""):
    """Fallback: use a VBScript InputBox via cscript (works on all Windows)."""
    try:
        import subprocess, tempfile
        # Escape quotes for VBScript string literals (double the double-quotes)
        _vesc = lambda s: s.replace('"', '""')
        vbs = f'WScript.Echo InputBox("{_vesc(prompt_text)}", "{_vesc(title)}", "{_vesc(default)}")'
        with tempfile.NamedTemporaryFile(mode='w', suffix='.vbs', delete=False) as f:
            f.write(vbs)
            vbs_path = f.name
        try:
            result = subprocess.run(
                ['cscript', '//Nologo', vbs_path],
                capture_output=True, text=True, timeout=120
            )
            return result.stdout.strip()
        finally:
            os.remove(vbs_path)
    except Exception as e:
        log.error(f"VBScript fallback failed: {e}")
        return ""


def _gui_alert(title, message):
    """Show an informational alert dialog."""
    if platform.system() == "Darwin":
        import subprocess
        # Convert literal \n to AppleScript newlines and escape quotes
        def _esc_as(s):
            s = s.replace('\\n', '\n')  # literal \n → real newline
            s = s.replace('"', '\\"')
            s = s.replace('\n', '" & return & "')  # real newline → AppleScript return
            return s
        script = (
            f'display dialog "{_esc_as(message)}" '
            f'with title "{_esc_as(title)}" '
            f'buttons {{"OK"}} default button "OK" '
            f'with icon note'
        )
        try:
            subprocess.run(['osascript', '-e', script], timeout=30)
        except Exception:
            pass
    elif platform.system() == "Windows":
        try:
            import ctypes
            # MB_OK | MB_ICONINFORMATION | MB_TOPMOST
            ctypes.windll.user32.MessageBoxW(
                0, message.replace('\\n', '\n'), title, 0x00000040 | 0x00040000
            )
        except Exception:
            try:
                import tkinter as tk
                from tkinter import messagebox
                root = tk.Tk()
                root.withdraw()
                root.attributes('-topmost', True)
                messagebox.showinfo(title, message.replace('\\n', '\n'), parent=root)
                root.destroy()
            except Exception:
                pass


def first_run_setup():
    """Interactive first-run: asks user for details, fetches API token."""
    import requests

    log.info("First-run setup starting...")

    server_url = _gui_prompt(
        "TimePulse Setup",
        "Enter your server URL:",
        "https://aitimekeeper.onrender.com"
    ).rstrip("/")
    if not server_url:
        _gui_alert("TimePulse", "Setup cancelled. The app will not track until configured.\\n\\nRestart the app to try again.")
        raise ValueError("Setup cancelled — no server URL.")

    user_email = _gui_prompt(
        "TimePulse Setup",
        "Enter your work email (must be registered by your admin):"
    )
    if not user_email:
        _gui_alert("TimePulse", "Setup cancelled. The app will not track until configured.\\n\\nRestart the app to try again.")
        raise ValueError("Setup cancelled — no email.")

    log.info(f"Provisioning token for {user_email} from {server_url}...")
    try:
        resp = requests.post(
            f"{server_url}/api/agent/provision",
            json={"email": user_email},
            timeout=30,
        )
        if resp.status_code == 403:
            _gui_alert("TimePulse — Error",
                        f"Email '{user_email}' is not registered.\\n\\nAsk your admin to add you in Admin → Users first, then restart the app.")
            raise ValueError(f"Email not registered: {user_email}")
        resp.raise_for_status()
        data = resp.json()
        api_token = data.get("token")
        if not api_token:
            raise ValueError("Server returned no token.")
        log.info("Token received successfully")
    except requests.exceptions.ConnectionError:
        _gui_alert("TimePulse — Error",
                    f"Could not connect to {server_url}.\\n\\nCheck your internet connection and server URL, then restart the app.")
        raise ValueError(f"Cannot connect to {server_url}")
    except requests.exceptions.Timeout:
        _gui_alert("TimePulse — Error",
                    f"Server at {server_url} took too long to respond.\\n\\nThe server may be starting up. Wait a minute and restart the app.")
        raise ValueError(f"Timeout connecting to {server_url}")
    except ValueError:
        raise  # re-raise our own ValueErrors
    except Exception as e:
        _gui_alert("TimePulse — Error",
                    f"Could not fetch token: {e}\\n\\nRestart the app to try again.")
        raise ValueError(f"Provisioning failed: {e}")

    cfg = {"server_url": server_url, "user_email": user_email, "api_token": api_token}
    save(cfg)
    tray_location = "menu bar" if platform.system() == "Darwin" else "system tray"
    _gui_alert("TimePulse — Ready!",
               f"Setup complete for {user_email}.\\n\\nThe agent is now tracking in the background. Look for the icon in your {tray_location}.")
    log.info(f"Config saved for {user_email}. Setup complete.")
    return cfg


def change_email():
    """Let user change their email. Re-provisions a new token."""
    import requests

    cfg = load()
    current_email = cfg.get('user_email', '')
    server_url = cfg.get('server_url', 'https://aitimekeeper.onrender.com')

    new_email = _gui_prompt(
        "TimePulse — Change Email",
        "Enter your new work email:",
        current_email
    )
    if not new_email or new_email == current_email:
        return None  # cancelled or unchanged

    log.info(f"Changing email from {current_email} to {new_email}...")
    try:
        resp = requests.post(
            f"{server_url}/api/agent/provision",
            json={"email": new_email},
            timeout=30,
        )
        if resp.status_code == 403:
            _gui_alert("TimePulse — Error",
                        f"Email '{new_email}' is not registered.\\n\\nAsk your admin to add you first.")
            return None
        resp.raise_for_status()
        data = resp.json()
        api_token = data.get("token")
        if not api_token:
            raise ValueError("No token returned")

        cfg["user_email"] = new_email
        cfg["api_token"] = api_token
        save(cfg)
        _gui_alert("TimePulse — Email Updated",
                   f"Email changed to {new_email}.\\n\\nLogs will now be tracked under the new email.")
        log.info(f"Email changed to {new_email}")
        return cfg
    except Exception as e:
        _gui_alert("TimePulse — Error", f"Could not update email: {e}")
        log.error(f"Email change failed: {e}")
        return None
