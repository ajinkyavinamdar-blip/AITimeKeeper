import pystray
from PIL import Image, ImageDraw, ImageFont
import webbrowser
import platform
import subprocess
import threading
import sys

class SystemTrayApp:
    def __init__(self, agent, flask_url="http://127.0.0.1:5001"):
        self.agent = agent
        self.flask_url = flask_url
        self.icon = None

    def create_image(self, color):
        # Generate an image for the icon
        width = 64
        height = 64
        # Use transparent background
        image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        dc = ImageDraw.Draw(image)
        
        if color == "gray":
            # Draw a pause symbol (two vertical bars)
            bar_width = 10
            bar_height = 30
            gap = 10
            x1 = (width - (2 * bar_width + gap)) // 2
            y1 = (height - bar_height) // 2
            dc.rectangle((x1, y1, x1 + bar_width, y1 + bar_height), fill="gray")
            dc.rectangle((x1 + bar_width + gap, y1, x1 + bar_width + gap + bar_width, y1 + bar_height), fill="gray")
        else:
            # Draw a simple rocket shape
            # Body (triangle + rect)
            cx, cy = width // 2, height // 2
            
            # Colors
            rocket_color = "white"
            fin_color = "red"
            window_color = "blue"

            # Main body (ellipse for more rocket like)
            dc.ellipse((cx - 10, cy - 20, cx + 10, cy + 15), fill=rocket_color)
            
            # Nose cone (triangle)
            # dc.polygon([(cx, cy - 30), (cx - 10, cy - 20), (cx + 10, cy - 20)], fill=rocket_color) 
            
            # Fins
            dc.polygon([(cx - 10, cy + 5), (cx - 20, cy + 20), (cx - 10, cy + 15)], fill=fin_color)
            dc.polygon([(cx + 10, cy + 5), (cx + 20, cy + 20), (cx + 10, cy + 15)], fill=fin_color)
            
            # Flame (orange triangle)
            dc.polygon([(cx - 5, cy + 15), (cx + 5, cy + 15), (cx, cy + 25)], fill="orange")
            
            # Window
            dc.ellipse((cx - 4, cy - 10, cx + 4, cy - 2), fill=window_color)

        return image

    def on_dashboard(self, icon, item):
        webbrowser.open(self.flask_url)

    def on_toggle_pause(self, icon, item):
        if self.agent.paused:
            self.agent.resume()
            self.icon.icon = self.create_image("green")
            self.send_notification("TimePulse", "Tracking Resumed")
        else:
            self.agent.pause()
            self.icon.icon = self.create_image("gray")
            self.send_notification("TimePulse", "Tracking Paused")

    def on_exit(self, icon, item):
        self.agent.stop()
        self.icon.stop()
        sys.exit(0)

    def send_notification(self, title, message):
        if platform.system() == "Darwin":
            try:
                subprocess.run(["osascript", "-e", f'display notification "{message}" with title "{title}"'])
            except Exception as e:
                print(f"Notification error: {e}")
        elif platform.system() == "Windows":
            try:
                from win10toast import ToastNotifier
                toaster = ToastNotifier()
                toaster.show_toast(title, message, duration=3, threaded=True)
            except ImportError:
                print("win10toast not installed")

    def run(self):
        # Menu items
        menu = pystray.Menu(
            pystray.MenuItem("Dashboard", self.on_dashboard),
            pystray.MenuItem("Pause / Resume", self.on_toggle_pause),
            pystray.MenuItem("Exit", self.on_exit)
        )

        self.icon = pystray.Icon(
            "TimePulse",
            self.create_image("green"),
            "TimePulse",
            menu
        )
        
        self.send_notification("TimePulse", "Agent Started")
        self.icon.run() 
