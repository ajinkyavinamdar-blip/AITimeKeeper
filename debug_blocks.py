from src.database import get_work_blocks, init_db
import datetime

try:
    print("Testing get_work_blocks...")
    blocks = get_work_blocks()
    print(f"Successfully retrieved {len(blocks)} blocks.")
    for b in blocks[:3]:
        print(b)
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
