from __future__ import annotations

import importlib
import os
import platform
import sys
import tempfile
from pathlib import Path

from .audio_inputs import (
    AudioInputDeviceError,
    audio_input_device_label,
    default_audio_input_device,
    list_audio_input_devices,
)
from .branding import APP_NAME
from .config import app_data_dir, load_settings


def run_diagnostics() -> None:
    settings = load_settings()

    print(f"Python version: {sys.version.replace(os.linesep, ' ')}")
    print(f"OS version: {platform.platform()}")
    print("Microphone input devices:")
    _print_microphone_devices(settings.audio_input_device)
    print(f"Configured model_size: {settings.model_size}")
    print(f"Configured device: {settings.device}")
    print(f"faster-whisper import: {_import_status('faster_whisper')}")
    print(f"ctranslate2 import: {_import_status('ctranslate2')}")
    print(f"sounddevice import: {_import_status('sounddevice')}")
    print(f"OPENAI_API_KEY present: {'yes' if os.getenv('OPENAI_API_KEY') else 'no'}")
    print(f"%TEMP%\\{APP_NAME} writable: {'yes' if _temp_dir_writable() else 'no'}")
    print(f"App data dir: {app_data_dir()}")
    print(f"Log file: {app_data_dir() / 'logs' / 'app.log'}")
    print(f"SSLKEYLOGFILE set: {_sslkeylogfile_status()}")
    print("Antivirus notes:")
    for line in _antivirus_notes():
        print(f"  - {line}")


def _print_microphone_devices(configured_device: int | None) -> None:
    try:
        devices = list_audio_input_devices()
    except AudioInputDeviceError as exc:
        print(
            f"  configured: {audio_input_device_label(configured_device)}"
        )
        print(f"  error: {exc}")
        return

    print(f"  configured: {audio_input_device_label(configured_device, devices)}")

    try:
        default_device = default_audio_input_device()
    except AudioInputDeviceError:
        default_device = None

    if not devices:
        print("  none found")
        return

    for device in devices:
        flags: list[str] = []
        if device.index == default_device:
            flags.append("system default")
        if configured_device is not None and device.index == configured_device:
            flags.append("selected")
        suffix = f"; {', '.join(flags)}" if flags else ""
        print(
            f"  {device.choice_label} ({device.input_channels} input channels{suffix})"
        )


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


def _sslkeylogfile_status() -> str:
    value = os.environ.get("SSLKEYLOGFILE")
    if not value:
        return "no"
    # Device-namespace paths (common with Norton TLS interception) break OpenSSL.
    if value.startswith("\\\\.\\"):
        return f"yes (device path; Speech strips this at startup) value={value!r}"
    return f"yes value={value!r}"


def _antivirus_notes() -> list[str]:
    notes = [
        "If stop/transcribe freezes, check antivirus real-time scanning.",
        "Norton and similar products may inject SSLKEYLOGFILE or scan model DLLs.",
        "Recommended exclusions: the Speech install folder, %APPDATA%\\Speech, "
        f"%TEMP%\\{APP_NAME}, and the Hugging Face cache (~/.cache/huggingface).",
    ]
    detected = _detect_security_products()
    if detected:
        notes.insert(0, f"Security products detected on this machine: {', '.join(detected)}.")
    else:
        notes.insert(0, "No well-known third-party AV service names detected via service list.")
    return notes


def _detect_security_products() -> list[str]:
    """Best-effort Windows service name scan; never fails diagnostics."""
    if os.name != "nt":
        return []
    try:
        import subprocess

        completed = subprocess.run(
            ["sc", "query", "type=", "service", "state=", "all"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
    except Exception:
        return []

    needles = {
        "Norton": ("Norton", "Norton Antivirus", "Norton Security"),
        "Avast": ("Avast",),
        "AVG": ("AVG",),
        "McAfee": ("McAfee",),
        "Bitdefender": ("Bitdefender",),
        "Kaspersky": ("Kaspersky",),
        "ESET": ("ESET",),
        "Malwarebytes": ("Malwarebytes",),
    }
    found: list[str] = []
    upper = output.upper()
    for label, patterns in needles.items():
        if any(pattern.upper() in upper for pattern in patterns):
            found.append(label)
    return found


if __name__ == "__main__":
    run_diagnostics()
    raise SystemExit(0)
