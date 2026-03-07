"""
observer_win.py — Windows activity observer for the desktop agent.
"""
from dataclasses import dataclass

try:
    import win32gui
    import win32process
    import psutil
except ImportError:
    win32gui = None
    win32process = None
    psutil = None

try:
    import uiautomation as auto
except ImportError:
    auto = None


@dataclass
class Activity:
    app_name: str
    window_title: str
    url_or_filename: str = ""
    chrome_profile: str = ""


class WindowsObserver:
    def get_current_activity(self) -> Activity:
        if not win32gui:
            return Activity("Error", "Missing Dependencies (pywin32 not installed)")

        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return Activity("Unknown", "No Active Window")

        window_title = win32gui.GetWindowText(hwnd)

        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            import psutil as _psutil
            app_name = _psutil.Process(pid).name()
        except Exception:
            app_name = "Unknown"

        url = ""
        if auto and ("chrome" in app_name.lower() or "msedge" in app_name.lower()):
            try:
                ctrl = auto.ControlFromHandle(hwnd)
                addr = ctrl.EditControl(Name="Address and search bar")
                if addr.Exists(0, 0):
                    url = addr.GetValuePattern().Value
            except Exception:
                pass

        return Activity(app_name=app_name, window_title=window_title, url_or_filename=url)
