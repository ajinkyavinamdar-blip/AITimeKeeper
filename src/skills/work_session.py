
import time
import datetime

class WorkSessionManager:
    def __init__(self):
        self.session_start = None
        self.last_active_time = time.time()
        self.break_threshold = 60 * 5 # 5 minutes idle = break
        self.current_break_duration = 0
        self.total_break_time = 0
        self.is_on_break = False
        
        # Start the session immediately (or detecting first activity)
        self.session_start = time.time()

    def update(self, is_idle: bool):
        now = time.time()
        
        if is_idle:
            if not self.is_on_break:
                # Check if idle long enough to trigger break
                if (now - self.last_active_time) > self.break_threshold:
                    self.is_on_break = True
                    self.current_break_duration = now - self.last_active_time
            else:
                self.current_break_duration += 5 # Add polling interval
        else:
            if self.is_on_break:
                # End of break
                self.total_break_time += self.current_break_duration
                self.current_break_duration = 0
                self.is_on_break = False
            
            self.last_active_time = now

    def get_stats(self):
        now = time.time()
        total_time = now - self.session_start
        
        # Calculate percentages
        work_time = total_time - self.total_break_time - self.current_break_duration
        
        return {
            "session_start": self.session_start,
            "total_work_time": work_time,
            "total_break_time": self.total_break_time,
            "is_on_break": self.is_on_break,
            "time_since_last_break": now - self.last_active_time if not self.is_on_break else 0
        }
