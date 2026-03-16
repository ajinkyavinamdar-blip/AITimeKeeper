"""
observer_mac.py — macOS activity observer for the desktop agent.
Mirrors src/monitoring/macos.py but is standalone (no relative imports).
"""
import re
import subprocess
from dataclasses import dataclass

# Strip invisible Unicode characters (LTR mark, RTL mark, zero-width space, etc.)
_INVISIBLE_RE = re.compile(r'[\u200e\u200f\u200b\u200c\u200d\u2060\ufeff]')


@dataclass
class Activity:
    app_name: str
    window_title: str
    url_or_filename: str = ""
    chrome_profile: str = ""


class MacObserver:
    def _run(self, script: str) -> str:
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, check=True, timeout=3
            )
            return result.stdout.strip()
        except Exception:
            return ""

    def get_current_activity(self) -> Activity:
        app_name_script = '''
        tell application "System Events"
            set frontProcess to first application process whose frontmost is True
            set appName to name of frontProcess
            try
                set displayedName to displayed name of frontProcess
            on error
                set displayedName to appName
            end try
            return displayedName & "|" & appName
        end tell
        '''
        result = self._run(app_name_script)
        if not result:
            return Activity("Unknown", "Unknown")

        parts = result.split("|")
        app_name = _INVISIBLE_RE.sub('', parts[0]).strip() if parts else "Unknown"

        window_title = self._run(
            f'tell application "System Events" to tell process "{app_name}" to get name of front window'
        )

        url = ""
        if app_name in ["Google Chrome", "Microsoft Edge", "Arc", "Brave Browser"]:
            url = self._run(f'tell application "{app_name}" to get URL of active tab of front window')
        elif app_name == "Safari":
            url = self._run('tell application "Safari" to get URL of document 1')

        filename = window_title if app_name in ["Microsoft Word", "Microsoft Excel"] else ""

        return Activity(
            app_name=app_name,
            window_title=_INVISIBLE_RE.sub('', window_title).strip(),
            url_or_filename=_INVISIBLE_RE.sub('', url or filename).strip(),
        )
