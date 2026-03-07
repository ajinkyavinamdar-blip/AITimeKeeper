from src.database import get_overtime_stats, get_todays_activities
import traceback

try:
    print("Testing get_overtime_stats...")
    stats = get_overtime_stats()
    print("Overtime Stats:", stats)
except Exception:
    traceback.print_exc()

try:
    print("\nTesting work_stats logic...")
    activities = get_todays_activities()
    start_time = activities[-1]['timestamp'] if activities else None
    print("Start Time:", start_time)
except Exception:
    traceback.print_exc()
