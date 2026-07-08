from __future__ import annotations

import importlib
import os
import platform
import sys
import tempfile
from pathlib import Path

from .branding import APP_NAME
from .config import load_settings


def run_diagnostics() -> None:
    settings = load_settings()

    print(f"Python version: {sys.version.replace(os.linesep, ' ')}")
    print(f"OS version: {platform.platform()}")
    print("Microphone input devices:")
    _print_microphone_devices()
    print(f"Configured model_size: {settings.model_size}")
    print(f"Configured device: {settings.device}")
    print(f"faster-whisper import: {_import_status('faster_whisper')}")
    print(f"OPENAI_API_KEY present: {'yes' if os.getenv('OPENAI_API_KEY') else 'no'}")
    print(f"%TEMP%\\{APP_NAME} writable: {'yes' if _temp_dir_writable() else 'no'}")


def _print_microphone_devices() -> None:
    try:
        sounddevice = importlib.import_module("sounddevice")
        devices = sounddevice.query_devices()
    except Exception as exc:
        print(f"  error: {exc.__class__.__name__}: {exc}")
        return

    found = False
    for index, device in enumerate(devices):
        if int(device.get("max_input_channels", 0)) <= 0:
            continue
        found = True
        name = device.get("name", "Unknown")
        channels = device.get("max_input_channels", "?")
        print(f"  [{index}] {name} ({channels} input channels)")

    if not found:
        print("  none found")


def _import_status(module_name: str) -> str:
    try:
        importlib.import_module(module_name)
    except Exception as exc:
        return f"no ({exc.__class__.__name__})"
    return "yes"


def _temp_dir_writable() -> bool:
    temp_dir = Path(tempfile.gettempdir()) / APP_NAME
    try:
        temp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=temp_dir):
            pass
    except OSError:
        return False
    return True


if __name__ == "__main__":
    run_diagnostics()
    raise SystemExit(0)
