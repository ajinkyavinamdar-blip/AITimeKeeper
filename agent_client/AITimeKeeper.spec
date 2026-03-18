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
        'pystray',
        'pystray._darwin',
        'pystray._win32',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'observer_mac',
        'observer_win',
        'config',
        'uploader',
        'objc',
        'Foundation',
        'AppKit',
        'win32gui',
        'win32process',
        'win32com',
        'win32com.client',
        'psutil',
        'uiautomation',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'scipy'],
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
    console=False,   # macOS apps must have console=False to open properly from Finder
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
            'LSUIElement': True,           # hide from Dock but still launchable from Finder
            'CFBundleShortVersionString': '1.4.8',
            'NSSupportsAutomaticTermination': False,
            'NSSupportsSuddenTermination': False,
            'CFBundleName': 'AITimeKeeper',
            'NSAppleEventsUsageDescription': 'Required to detect active app and window for time tracking.',
            'NSMicrophoneUsageDescription': 'Not used.',
        },
    )
