"""
observer_mac.py — macOS activity observer for the desktop agent.
Mirrors src/monitoring/macos.py but is standalone (no relative imports).

Uses NSWorkspace (Cocoa) for reliable app detection — never returns "Unknown"
for a visible app. Falls back to AppleScript only for window title / URL.
"""
import re
import subprocess
import logging
from dataclasses import dataclass

log = logging.getLogger("observer_mac")

# Strip invisible Unicode characters (LTR mark, RTL mark, zero-width space, etc.)
_INVISIBLE_RE = re.compile(r'[\u200e\u200f\u200b\u200c\u200d\u2060\ufeff]')


@dataclass
class Activity:
    app_name: str
    window_title: str
    url_or_filename: str = ""
    chrome_profile: str = ""


def _get_frontmost_app_cocoa():
    """Use NSWorkspace to get the frontmost app name — instant, never times out."""
    try:
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app:
            return app.localizedName() or app.bundleIdentifier() or ""
    except ImportError:
        pass
    except Exception as e:
        log.debug(f"NSWorkspace fallback: {e}")
    return ""


class MacObserver:
    def _run(self, script: str, timeout: int = 3) -> str:
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, check=True, timeout=timeout
            )
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            log.debug("AppleScript timed out")
            return ""
        except Exception:
            return ""

    def _get_app_name(self) -> str:
        """Get frontmost app name.  Primary: NSWorkspace (instant).
        Fallback: AppleScript (slower but works without pyobjc)."""
        # --- fast path: Cocoa ---
        name = _get_frontmost_app_cocoa()
        if name:
            return _INVISIBLE_RE.sub('', name).strip()

        # --- slow path: AppleScript ---
        script = '''
        tell application "System Events"
            set frontProcess to first application process whose frontmost is True
            try
                set displayedName to displayed name of frontProcess
            on error
                set displayedName to name of frontProcess
            end try
            return displayedName
        end tell
        '''
        result = self._run(script)
        if result:
            return _INVISIBLE_RE.sub('', result).strip()
        return "Unknown"

    def _get_process_name(self) -> str:
        """Get the process name (used to address the process in System Events).
        May differ from the displayed / localised name."""
        script = '''
        tell application "System Events"
            return name of first application process whose frontmost is True
        end tell
        '''
        result = self._run(script)
        return _INVISIBLE_RE.sub('', result).strip() if result else ""

    def get_current_activity(self) -> Activity:
        app_name = self._get_app_name()
        if app_name == "Unknown":
            return Activity("Unknown", "Unknown")

        # For addressing the process in System Events we need the process name,
        # which can differ from the displayed name.  Try to get it, but if it
        # times out just use app_name (works 99% of the time).
        process_name = self._get_process_name() or app_name

        # Window title — use process_name to address the process
        window_title = self._run(
            f'tell application "System Events" to tell process "{process_name}" '
            f'to get name of front window'
        )
        # If window title fails, still keep the app_name (don't fall back to Unknown)
        if not window_title:
            window_title = app_name

        url = ""
        filename = ""

        if app_name in ["Google Chrome", "Microsoft Edge", "Arc", "Brave Browser"]:
            url = self._run(
                f'tell application "{app_name}" to get URL of active tab of front window'
            )
        elif app_name == "Safari":
            url = self._run('tell application "Safari" to get URL of document 1')
        elif app_name == "Microsoft Excel":
            filename = self._run(
                'tell application "Microsoft Excel" to get name of active workbook'
            )
            if not filename:
                filename = window_title
        elif app_name == "Microsoft Word":
            filename = self._run(
                'tell application "Microsoft Word" to get name of active document'
            )
            if not filename:
                filename = window_title
        elif app_name == "Microsoft PowerPoint":
            filename = self._run(
                'tell application "Microsoft PowerPoint" to get name of active presentation'
            )
            if not filename:
                filename = window_title
        elif app_name in ["Numbers", "Pages", "Keynote"]:
            filename = self._run(
                f'tell application "{app_name}" to get name of front document'
            )
            if not filename:
                filename = window_title
        elif app_name == "Preview":
            filename = self._run(
                'tell application "Preview" to get name of front document'
            )
            if not filename:
                filename = window_title
        elif app_name == "Finder":
            filename = self._run(
                'tell application "Finder" to get POSIX path of '
                '(target of front Finder window as alias)'
            )
            if not filename:
                filename = window_title
        elif app_name in ["Microsoft Teams", "Microsoft Teams (work or school)",
                          "Microsoft Teams classic"]:
            filename = window_title

        return Activity(
            app_name=app_name,
            window_title=_INVISIBLE_RE.sub('', window_title).strip(),
            url_or_filename=_INVISIBLE_RE.sub('', url or filename).strip(),
        )
