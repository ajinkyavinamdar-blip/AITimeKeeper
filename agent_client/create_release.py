#!/usr/bin/env python3
"""
create_release.py — Create a GitHub Release and upload the Mac .zip binary.
Run: python3 create_release.py <GITHUB_TOKEN>
"""
import sys, os, json, mimetypes
import urllib.request, urllib.error

REPO = "ajinkyavinamdar-blip/AITimeKeeper"
TAG = "v1.4.4"
RELEASE_NAME = "v1.4.4 — Fix Logs Stopping at Hour Mark"
RELEASE_BODY = """## TimePulse Desktop Agent v1.4.4

### What's New

**Critical Fix: Logs No Longer Stop at ~30-60 Minutes**
- Root cause identified: pynput idle filter falsely marked user as permanently idle when macOS Accessibility permission was not granted
- After ~3 minutes with no input events, the idle filter would think the user is idle and stop tracking — permanently
- Now: idle detection gracefully degrades — if no input events received for 5 minutes, idle filter auto-disables and tracking runs continuously
- Agent will always track activity even without Accessibility permission (just without idle detection)

**Control Poll Hardening**
- Fixed crash when server returns non-JSON responses (e.g., during Render cold starts)
- Reduced log spam from repeated poll errors
- Auto-disables poll if endpoint returns 404

### Download & Install
- **Mac**: Download `TimePulse-Mac-1.4.4.zip`, unzip, drag to Applications
  - First time: right-click → Open (to bypass Gatekeeper)

### First Run
When you open the agent for the first time, it will ask you:
1. Your server URL: `https://aitimekeeper.onrender.com`
2. Your work email address

It will automatically fetch your API token and start tracking.
"""

DIST_DIR = os.path.join(os.path.dirname(__file__), "dist")
MAC_ZIP = os.path.join(DIST_DIR, "TimePulse-Mac-1.4.4.zip")

def gh_request(token, method, path, data=None, binary=None, content_type="application/json"):
    url = f"https://api.github.com{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "TimePulse-Build",
        "Content-Type": content_type,
    }
    body = binary if binary else (json.dumps(data).encode() if data else None)
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        resp = e.read().decode()
        print(f"HTTP {e.code}: {resp}")
        sys.exit(1)

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 create_release.py <GITHUB_TOKEN>")
        print("Get a token at: https://github.com/settings/tokens/new")
        print("Required scope: repo (full control of private repos)")
        sys.exit(1)

    token = sys.argv[1].strip()

    # 1. Check if release already exists
    print(f"Checking for existing release {TAG}...")
    releases, _ = gh_request(token, "GET", f"/repos/{REPO}/releases")
    existing = next((r for r in releases if r["tag_name"] == TAG), None)

    if existing:
        print(f"Release {TAG} already exists (id={existing['id']}). Using it.")
        release = existing
    else:
        # 2. Create release
        print(f"Creating release {TAG}...")
        release, status = gh_request(token, "POST", f"/repos/{REPO}/releases", {
            "tag_name": TAG,
            "name": RELEASE_NAME,
            "body": RELEASE_BODY,
            "draft": False,
            "prerelease": False,
        })
        print(f"Release created: {release['html_url']}")

    # 3. Upload Mac .zip
    if not os.path.exists(MAC_ZIP):
        print(f"ERROR: {MAC_ZIP} not found. Run PyInstaller first.")
        sys.exit(1)

    # Check if asset already uploaded
    assets, _ = gh_request(token, "GET", f"/repos/{REPO}/releases/{release['id']}/assets")
    mac_asset = next((a for a in assets if "Mac" in a["name"]), None)
    if mac_asset:
        print(f"Mac asset already uploaded: {mac_asset['browser_download_url']}")
    else:
        print(f"Uploading {os.path.basename(MAC_ZIP)} ({os.path.getsize(MAC_ZIP)//1024//1024}MB)...")
        with open(MAC_ZIP, "rb") as f:
            data = f.read()
        upload_url = f"https://uploads.github.com/repos/{REPO}/releases/{release['id']}/assets?name={os.path.basename(MAC_ZIP)}"
        req = urllib.request.Request(
            upload_url, data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/zip",
                "Accept": "application/vnd.github+json",
                "User-Agent": "TimePulse-Build",
            },
            method="POST"
        )
        with urllib.request.urlopen(req) as r:
            result = json.loads(r.read())
        print(f"✅ Uploaded: {result['browser_download_url']}")

    print()
    print("=== Release complete! ===")
    print(f"URL: {release['html_url']}")

if __name__ == "__main__":
    main()
