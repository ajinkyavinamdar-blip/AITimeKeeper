@echo off
REM build_windows.bat — Build AITimeKeeper.exe for Windows using PyInstaller

echo Installing dependencies...
pip install pyinstaller
pip install -r requirements.txt

echo Building Windows executable...
pyinstaller ^
  --onefile ^
  --name AITimeKeeper ^
  --add-data "config.py;." ^
  --add-data "uploader.py;." ^
  --add-data "observer_win.py;." ^
  --hidden-import "pynput.mouse._win32" ^
  --hidden-import "pynput.keyboard._win32" ^
  --noconsole ^
  main.py

echo.
echo Build complete! Output: dist\AITimeKeeper.exe
