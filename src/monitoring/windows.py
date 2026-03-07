from .base import BaseObserver, Activity
import sys

# Safe imports for Windows libraries
try:
    import win32gui
    import win32process
    import uiautomation as auto
except ImportError:
    win32gui = None
    win32process = None
    auto = None

class WindowsObserver(BaseObserver):
    def __init__(self):
        if not win32gui:
            print("Warning: pywin32 not installed. Windows monitoring will not work.")

    def get_current_activity(self) -> Activity:
        if not win32gui:
            return Activity("Error", "Missing Dependencies")

        window = win32gui.GetForegroundWindow()
        if not window:
            return Activity("Unknown", "No Active Window")
            
        window_title = win32gui.GetWindowText(window)
        # simplistic app name extraction (would need process ID to be accurate)
        # For better accuracy: use win32process to get pid, then psutil to get exe name
        # Here just using window title or assuming. 
        # Let's try to get generation process name
        
        try:
            _, pid = win32process.GetWindowThreadProcessId(window)
            import psutil
            process = psutil.Process(pid)
            app_name = process.name()
        except:
            app_name = "Unknown"

        url = ""
        
        # Browser Context
        if "chrome" in app_name.lower() or "edge" in app_name.lower():
            try:
                # Basic uiautomation to get address bar
                # This is heavy and might be slow every 5s, usually better to cache control
                control = auto.ControlFromHandle(window)
                addr_bar = control.EditControl(Name='Address and search bar')
                if addr_bar.Exists(0, 0):
                    url = addr_bar.GetValuePattern().Value
            except:
                pass
                
        return Activity(
            app_name=app_name,
            window_title=window_title,
            url_or_filename=url
        )
