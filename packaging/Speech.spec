# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)

ROOT = Path.cwd()
SRC = ROOT / "src"

hiddenimports = (
    [
        "winwhisper.native_overlay",
        "pynput._util.win32",
        "pynput.keyboard._win32",
        "pynput.mouse._win32",
        "pystray._win32",
    ]
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
