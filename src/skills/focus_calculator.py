
from collections import deque
import time

class FocusCalculator:
    def __init__(self):
        # Configuration
        self.focus_threshold_seconds = 60 * 5 # 5 minutes of focus category to count as "Flow"
        self.interruption_threshold_seconds = 30 # Short switch to distraction
        
        # State
        self.activity_history = deque(maxlen=20) # Keep last 20 activities (approx 100 seconds)
        self.focus_duration = 0
        self.total_interruptions = 0
        self.current_state = "neutral" # focus, neutral, distraction
        self.last_switch_time = time.time()
    
    def update(self, category_name: str, is_focus: bool, is_distraction: bool):
        now = time.time()
        
        # Determine current activity type
        activity_type = "neutral"
        if is_focus:
            activity_type = "focus"
        elif is_distraction:
            activity_type = "distraction"
            
        # Detect State Change
        if activity_type != self.current_state:
            # Check for interruption
            if self.current_state == "focus" and activity_type == "distraction":
                self.total_interruptions += 1
            
            self.current_state = activity_type
            self.last_switch_time = now
            
        # Update Focus Duration
        if self.current_state == "focus":
            self.focus_duration += 5 # Assuming 5s poll interval
            
    def get_stats(self):
        # Simple quality score algorithm
        # Quality = (Focus Time / (Focus Time + Distraction Time + Neutral Time)) * 100
        # For now, let's just return what we have
        return {
            "focus_duration": self.focus_duration,
            "interruptions": self.total_interruptions,
            "current_state": self.current_state
        }
