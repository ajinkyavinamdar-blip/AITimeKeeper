from pynput import mouse, keyboard
import time
import threading

class IdleFilter:
    def __init__(self, idle_threshold_seconds=180):
        self.last_activity = time.time()
        self.threshold = idle_threshold_seconds
        self.mouse_listener = mouse.Listener(on_move=self._on_activity, on_click=self._on_activity, on_scroll=self._on_activity)
        self.key_listener = keyboard.Listener(on_press=self._on_activity)
        
    def _on_activity(self, *args):
        self.last_activity = time.time()

    def start(self):
        self.mouse_listener.start()
        self.key_listener.start()

    def stop(self):
        self.mouse_listener.stop()
        self.key_listener.stop()

    def is_idle(self) -> bool:
        return (time.time() - self.last_activity) > self.threshold
