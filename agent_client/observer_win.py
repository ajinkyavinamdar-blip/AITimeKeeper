"""
observer_win.py — Windows activity observer for the desktop agent.
Uses pywin32 + psutil for foreground window detection, uiautomation for
browser URL extraction, and win32com for Office file names.
"""
import re
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

# Strip invisible Unicode characters
_INVISIBLE_RE = re.compile(r'[\u200e\u200f\u200b\u200c\u200d\u2060\ufeff]')


@dataclass
class Activity:
    app_name: str
    window_title: str
    url_or_filename: str = ""
    chrome_profile: str = ""


class WindowsObserver:

    def _get_office_filename(self, app_key: str, collection_attr: str) -> str:
        """Use win32com to get the active document/workbook name from an Office app.
        app_key: e.g. 'Excel.Application', 'Word.Application', 'PowerPoint.Application'
        collection_attr: e.g. 'ActiveWorkbook', 'ActiveDocument', 'ActivePresentation'
        """
        try:
            import win32com.client
            app = win32com.client.GetActiveObject(app_key)
            doc = getattr(app, collection_attr, None)
            if doc:
                return doc.Name or ""
        except Exception:
            pass
        return ""

    def get_current_activity(self) -> Activity:
        if not win32gui:
            return Activity("Error", "Missing Dependencies (pywin32 not installed)")

        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return Activity("Unknown", "No Active Window")

        window_title = win32gui.GetWindowText(hwnd)

        # Get process name
        app_name = "Unknown"
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc = psutil.Process(pid)
            app_name = proc.name()
        except Exception:
            pass

        # Friendly display name (strip .exe)
        display_name = app_name
        exe_lower = app_name.lower()

        # Map common exe names to friendly names
        _NAME_MAP = {
            'chrome.exe': 'Google Chrome',
            'msedge.exe': 'Microsoft Edge',
            'firefox.exe': 'Firefox',
            'brave.exe': 'Brave Browser',
            'excel.exe': 'Microsoft Excel',
            'winword.exe': 'Microsoft Word',
            'powerpnt.exe': 'Microsoft PowerPoint',
            'teams.exe': 'Microsoft Teams',
            'ms-teams.exe': 'Microsoft Teams',
            'explorer.exe': 'File Explorer',
            'code.exe': 'Visual Studio Code',
            'devenv.exe': 'Visual Studio',
            'slack.exe': 'Slack',
            'outlook.exe': 'Microsoft Outlook',
            'onenote.exe': 'Microsoft OneNote',
            'notepad.exe': 'Notepad',
            'notepad++.exe': 'Notepad++',
        }
        display_name = _NAME_MAP.get(exe_lower, app_name.replace('.exe', ''))

        url = ""
        filename = ""

        # --- Browser URL extraction ---
        if exe_lower in ('chrome.exe', 'msedge.exe', 'brave.exe'):
            if auto:
                try:
                    ctrl = auto.ControlFromHandle(hwnd)
                    addr = ctrl.EditControl(Name="Address and search bar")
                    if addr.Exists(0, 0):
                        url = addr.GetValuePattern().Value
                except Exception:
                    pass
        elif exe_lower == 'firefox.exe':
            if auto:
                try:
                    ctrl = auto.ControlFromHandle(hwnd)
                    # Firefox uses a different UI tree
                    for edit in ctrl.GetChildren():
                        if edit.ControlTypeName == 'ToolBarControl':
                            for child in edit.GetChildren():
                                if child.ControlTypeName == 'EditControl':
                                    url = child.GetValuePattern().Value
                                    break
                            if url:
                                break
                except Exception:
                    pass

        # --- Office file name extraction ---
        elif exe_lower == 'excel.exe':
            filename = self._get_office_filename('Excel.Application', 'ActiveWorkbook')
            if not filename:
                # Fallback: parse from window title (e.g. "Book1 - Excel")
                filename = window_title.rsplit(' - ', 1)[0].strip() if ' - ' in window_title else window_title

        elif exe_lower == 'winword.exe':
            filename = self._get_office_filename('Word.Application', 'ActiveDocument')
            if not filename:
                filename = window_title.rsplit(' - ', 1)[0].strip() if ' - ' in window_title else window_title

        elif exe_lower == 'powerpnt.exe':
            filename = self._get_office_filename('PowerPoint.Application', 'ActivePresentation')
            if not filename:
                filename = window_title.rsplit(' - ', 1)[0].strip() if ' - ' in window_title else window_title

        elif exe_lower == 'outlook.exe':
            # Outlook: window title shows current view/email subject
            filename = window_title.rsplit(' - ', 1)[0].strip() if ' - ' in window_title else window_title

        # --- Teams: channel/chat from window title ---
        elif exe_lower in ('teams.exe', 'ms-teams.exe'):
            filename = window_title

        # --- File Explorer: path from window title ---
        elif exe_lower == 'explorer.exe':
            filename = window_title

        # Clean invisible chars
        window_title = _INVISIBLE_RE.sub('', window_title).strip()
        detail = _INVISIBLE_RE.sub('', url or filename).strip()

        return Activity(
            app_name=display_name,
            window_title=window_title,
            url_or_filename=detail,
        )
