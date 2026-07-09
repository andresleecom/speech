# -*- mode: python ; coding: utf-8 -*-

import sys
import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)

ROOT = Path.cwd()
SRC = ROOT / "src"

APP_VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
    "project"
]["version"]

if sys.platform == "darwin":
    platform_hiddenimports = [
        "winwhisper.native_overlay_mac",
        "pynput._util.darwin",
        "pynput.keyboard._darwin",
        "pynput.mouse._darwin",
        "pystray._darwin",
    ]
else:
    platform_hiddenimports = [
        "winwhisper.native_overlay",
        "pynput._util.win32",
        "pynput.keyboard._win32",
        "pynput.mouse._win32",
        "pystray._win32",
    ]

hiddenimports = (
    platform_hiddenimports
    + collect_submodules("faster_whisper")
    + collect_submodules("ctranslate2")
)

datas = (
    collect_data_files("faster_whisper")
    + copy_metadata("faster-whisper")
    + copy_metadata("ctranslate2")
    + copy_metadata("speech")
)

binaries = collect_dynamic_libs("ctranslate2")

a = Analysis(
    [str(ROOT / "packaging" / "speech_launcher.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Speech",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Speech",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Speech.app",
        icon=None,
        bundle_identifier="com.andreslee.speech",
        version=APP_VERSION,
        info_plist={
            # Menu-bar app: no Dock icon, no app-switcher entry.
            "LSUIElement": True,
            "NSMicrophoneUsageDescription": (
                "Speech records your microphone only while you dictate."
            ),
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
        },
    )
