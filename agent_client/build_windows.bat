@echo off
REM build_windows.bat — Build TimePulse Windows agent (.exe)
REM Run this on a Windows machine. Requires Python 3.9+.
REM Usage: build_windows.bat [version]

setlocal
set VERSION=%1
if "%VERSION%"=="" set VERSION=1.0.0
set APP_NAME=TimePulse
set EXE_NAME=%APP_NAME%-Windows-%VERSION%.exe

echo === TimePulse Windows Build ===
echo Version: %VERSION%
echo.

REM 1. Install dependencies
echo Installing Python dependencies...
pip install pyinstaller pynput requests pywin32 psutil uiautomation pystray Pillow -q
if errorlevel 1 ( echo Failed to install dependencies && exit /b 1 )

REM 2. Clean previous builds
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build
if exist __pycache__ rmdir /s /q __pycache__

REM 3. Build with spec file
echo Running PyInstaller...
pyinstaller AITimeKeeper.spec --clean --noconfirm
if errorlevel 1 ( echo PyInstaller build failed && exit /b 1 )

REM 4. Rename output
if exist "dist\%APP_NAME%.exe" (
    move "dist\%APP_NAME%.exe" "dist\%EXE_NAME%"
    echo Built dist\%EXE_NAME%
) else (
    echo ERROR: dist\%APP_NAME%.exe not found
    exit /b 1
)

echo.
echo === Done! Upload dist\%EXE_NAME% to GitHub Releases ===
echo    https://github.com/ajinkyavinamdar-blip/AITimeKeeper/releases
endlocal
