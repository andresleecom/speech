"""Windows "Start at login" via HKCU Run. No-op on other platforms."""

from __future__ import annotations

import sys

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "Speech"


def installed_executable() -> str | None:
    """Return ``sys.executable`` only for the frozen installed app on Windows.

    From a source checkout ``sys.executable`` is the interpreter, which must
    not be registered for start-at-login.
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return None
    return sys.executable


def is_enabled() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
    except ImportError:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, _VALUE_NAME)
        return True
    except OSError:
        return False


def enable(exe_path: str) -> bool:
    """Write the HKCU Run value. ``exe_path`` is stored quoted."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
    except ImportError:
        return False
    quoted = f'"{exe_path}"'
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, quoted)
        return True
    except OSError:
        return False


def disable() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
    except ImportError:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, _VALUE_NAME)
        return True
    except OSError:
        return False
