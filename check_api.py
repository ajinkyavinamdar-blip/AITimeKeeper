import urllib.request
import json

endpoints = [
    '/api/activities',
    '/api/focus_stats',
    '/api/work_stats',
    '/api/summary',
    '/api/work_blocks',
    '/api/status'
]

base_url = "http://127.0.0.1:5001"

print("Checking API Endpoints...")
for ep in endpoints:
    url = base_url + ep
    try:
        with urllib.request.urlopen(url) as response:
            if response.status == 200:
                data = response.read()
                try:
                    json_data = json.loads(data)
                    print(f"[OK] {ep} - Valid JSON (Size: {len(data)})")
                except json.JSONDecodeError:
                    print(f"[ERR] {ep} - Invalid JSON")
            else:
                print(f"[ERR] {ep} - Status {response.status}")
    except Exception as e:
        print(f"[FAIL] {ep} - {e}")
