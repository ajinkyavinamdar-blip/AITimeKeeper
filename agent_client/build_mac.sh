#!/bin/bash
# build_mac.sh — Build TimePulse macOS agent (.dmg installer)
# Usage: bash build_mac.sh
set -e
cd "$(dirname "$0")"

VERSION="${1:-1.0.0}"
APP_NAME="TimePulse"
DMG_NAME="${APP_NAME}-Mac-${VERSION}.dmg"

echo "=== TimePulse macOS Build ==="
echo "Version: $VERSION"
echo ""

# 1. Install dependencies
echo "▶ Installing Python dependencies..."
pip3 install pyinstaller pynput requests pyobjc-framework-Cocoa psutil pystray Pillow -q

# 2. Clean previous build
rm -rf dist build __pycache__ *.pyc

# 3. Build with spec file
echo "▶ Running PyInstaller..."
pyinstaller AITimeKeeper.spec --clean --noconfirm

# 4. Verify build
if [ ! -d "dist/${APP_NAME}.app" ]; then
    echo "✗ .app bundle not found in dist/. Build may have failed."
    exit 1
fi
echo "✓ Built dist/${APP_NAME}.app"

# 5. Create .dmg
if command -v create-dmg &>/dev/null; then
    echo "▶ Creating .dmg installer..."
    create-dmg \
        --volname "${APP_NAME} Installer" \
        --window-pos 200 120 \
        --window-size 500 300 \
        --icon-size 100 \
        --icon "${APP_NAME}.app" 125 130 \
        --hide-extension "${APP_NAME}.app" \
        --app-drop-link 375 130 \
        "dist/${DMG_NAME}" \
        "dist/${APP_NAME}.app"
    echo "✓ Created dist/${DMG_NAME}"
else
    echo ""
    echo "⚠ create-dmg not found. Install it with:"
    echo "   /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    echo "   brew install create-dmg"
    echo ""
    echo "  Then re-run this script."
    echo ""
    echo "Alternatively, zip the .app for now:"
    cd dist && zip -r "${APP_NAME}-Mac-${VERSION}.zip" "${APP_NAME}.app" && cd ..
    echo "✓ Created dist/${APP_NAME}-Mac-${VERSION}.zip"
fi

echo ""
echo "=== Done! Upload dist/${DMG_NAME} (or .zip) to GitHub Releases ==="
