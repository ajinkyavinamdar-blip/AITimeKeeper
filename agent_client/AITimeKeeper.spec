# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for AITimeKeeper Desktop Agent
import sys, os

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[
        'pynput.mouse._darwin',
        'pynput.keyboard._darwin',
        'pynput.mouse._win32',
        'pynput.keyboard._win32',
        'observer_mac',
        'observer_win',
        'config',
        'uploader',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'scipy', 'PIL'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AITimeKeeper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,   # keep True so first-run prompts work in Terminal
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

# macOS: also create a .app bundle
if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name='AITimeKeeper.app',
        icon=None,
        bundle_identifier='com.aitimekeeper.agent',
        info_plist={
            'NSPrincipalClass': 'NSApplication',
            'LSBackgroundOnly': True,
            'LSUIElement': True,           # hide from Dock
            'CFBundleShortVersionString': '1.0.0',
            'CFBundleName': 'AITimeKeeper',
            'NSAppleEventsUsageDescription': 'Required to detect active app and window for time tracking.',
            'NSMicrophoneUsageDescription': 'Not used.',
        },
    )
