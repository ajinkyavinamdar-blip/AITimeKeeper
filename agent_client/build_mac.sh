#!/bin/bash
# build_mac.sh — Build AITimeKeeper.app for macOS using PyInstaller

set -e
cd "$(dirname "$0")"

echo "Installing dependencies..."
pip3 install pyinstaller -q
pip3 install -r requirements.txt -q

echo "Building macOS app..."
pyinstaller \
  --onefile \
  --name "AITimeKeeper" \
  --add-data "config.py:." \
  --add-data "uploader.py:." \
  --add-data "observer_mac.py:." \
  --hidden-import "pynput.mouse._darwin" \
  --hidden-import "pynput.keyboard._darwin" \
  main.py

echo ""
echo "Build complete! Output: dist/AITimeKeeper"
echo ""
echo "To create a .dmg, install create-dmg:"
echo "  brew install create-dmg"
echo "  create-dmg dist/AITimeKeeper-Mac.dmg dist/AITimeKeeper"
