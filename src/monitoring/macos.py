import subprocess
import time
from .base import BaseObserver, Activity

class MacObserver(BaseObserver):
    def _run_applescript(self, script):
        try:
            result = subprocess.run(
                ["osascript", "-e", script], 
                capture_output=True, 
                text=True, 
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return ""

    def get_current_activity(self) -> Activity:
        # 1. Get Frontmost App Name
        # Try to get the displayed name first, which is often more accurate for Electron apps
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
        result = self._run_applescript(app_name_script)
        if result:
            parts = result.split("|")
            app_name = parts[0]
            process_name = parts[1] if len(parts) > 1 else app_name
            
            # Specific fix for "Electron" or generic names
            if app_name == "Electron":
                 # If displayed name is "Electron", try to use the bundle name or fallback to window title later
                 # But usually 'displayed name' helps. If not, let's keep it as is for now
                 # and maybe use the window title heuristic if needed. 
                 pass
        else:
            app_name = ""

        if not app_name:
            return Activity("Unknown", "Unknown")

        window_title = ""
        url = ""
        filename = "" 

        # 2. Get Window Title
        try:
            title_script = f'tell application "System Events" to tell process "{app_name}" to get name of front window'
            window_title = self._run_applescript(title_script)
        except:
            window_title = ""

        # 3. Browser Context (Chrome, Edge, Arc, Safari)
        if app_name in ["Google Chrome", "Microsoft Edge", "Arc", "Brave Browser"]:
            try:
                # Chromium based
                url_script = f'tell application "{app_name}" to get URL of active tab of front window'
                url = self._run_applescript(url_script)
            except:
                pass
        elif app_name == "Safari":
            try:
                url_script = 'tell application "Safari" to get URL of document 1'
                url = self._run_applescript(url_script)
            except:
                pass

        # 4. App Context (Word, Excel) - simplified for now
        # Could use specific AppleScript for Word/Excel to get active document path
        if app_name in ["Microsoft Word", "Microsoft Excel"]:
             # Often the window title contains the filename, so we can rely on window_title for now
             # Or attempt to get document name specifically if needed
             filename = window_title

        return Activity(
            app_name=app_name,
            window_title=window_title,
            url_or_filename=url or filename
        )
