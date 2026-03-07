import platform
import time
import threading
import datetime
from .database import init_db, log_activity

# Import Observers
from .monitoring.base import BaseObserver

class TimeKeeperAgent:
    def __init__(self):
        self.running = False
        self.paused = False
        self.os_type = platform.system()
        self.observer = self._get_observer()
        init_db()

    def _get_observer(self) -> BaseObserver:
        if self.os_type == 'Darwin':
            from .monitoring.macos import MacObserver
            return MacObserver()
        elif self.os_type == 'Windows':
            from .monitoring.windows import WindowsObserver
            return WindowsObserver()
        else:
            print(f"Unsupported OS: {self.os_type}")
            return None

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread.is_alive():
            self.thread.join()

    def pause(self):
        self.paused = True
        print("Agent paused.")

    def resume(self):
        self.paused = False
        print("Agent resumed.")

    def get_status(self):
        return "paused" if self.paused else "running"

    def _loop(self):
        print(f"Agent started on {self.os_type}")

        while self.running:
            try:
                self._run_tracking_session()
            except Exception as e:
                print(f"[Agent] Tracking session crashed: {e}. Restarting in 10s...")
                time.sleep(10)

    def _run_tracking_session(self):
        # Skills Initialization
        from .skills.idle_filter import IdleFilter
        from .skills.client_mapper import ClientMapper
        from .skills.category_mapper import CategoryMapper
        from .skills.focus_calculator import FocusCalculator
        from .skills.work_session import WorkSessionManager
        
        idle_filter = IdleFilter()
        idle_filter.start()
        client_mapper = ClientMapper()
        category_mapper = CategoryMapper()
        
        # New Skills
        focus_calculator = FocusCalculator()
        work_session = WorkSessionManager()
        
        try:
            while self.running:
                if self.paused:
                    time.sleep(1)
                    continue

                is_idle = idle_filter.is_idle()
                
                # Update Work Session (handles breaks)
                work_session.update(is_idle)
                
                if self.observer:
                    if is_idle:
                        # print("User is idle. Skipping logging.")
                        pass
                    else:
                        try:
                            activity = self.observer.get_current_activity()
                            
                            # Skill: Client Mapper
                            client = client_mapper.resolve(activity.app_name, activity.window_title, activity.url_or_filename) or "Unassigned"
                            
                            # Skill: Category Mapper
                            category, category_id = category_mapper.resolve(activity.app_name, activity.window_title, activity.url_or_filename)
                            
                            # Skill: Focus Calculator
                            is_focus = False
                            is_distraction = False
                            # TODO: Fetch properties. For MVP, we can rely on defaults or cache.
                            
                            focus_calculator.update(category, is_focus, is_distraction)
                            
                            log_data = {
                                'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                'app_name': activity.app_name,
                                'window_title': activity.window_title,
                                'url_or_filename': activity.url_or_filename,
                                'chrome_profile': activity.chrome_profile,
                                'client': client,
                                'duration': 5.0, # Check interval
                                'category_id': category_id
                            }
                            log_activity(log_data)
                            # print(f"Logged: {activity.app_name} - {activity.window_title} ({client}) [{category}]")
                        except Exception as e:
                            print(f"Error in tracking loop: {e}")
                
                time.sleep(5)
        finally:
            idle_filter.stop()
