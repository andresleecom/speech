from __future__ import annotations

import os
import time

from .logger import get_logger

WindowHandle = int


def get_foreground_window() -> WindowHandle | None:
    if os.name != "nt":
        return None

    try:
        import ctypes

        hwnd = ctypes.windll.user32.GetForegroundWindow()
    except Exception as exc:
        get_logger(__name__).warning(
            "Could not capture foreground window: %s.",
            exc.__class__.__name__,
        )
        return None

    return int(hwnd) or None


def restore_foreground_window(hwnd: WindowHandle | None) -> bool:
    if os.name != "nt" or hwnd is None:
        return False

    try:
        import ctypes

        user32 = ctypes.windll.user32
        if not user32.IsWindow(hwnd):
            return False
        user32.ShowWindow(hwnd, 5)
        restored = bool(user32.SetForegroundWindow(hwnd))
        if restored:
            time.sleep(0.15)
        return restored
    except Exception as exc:
        get_logger(__name__).warning(
            "Could not restore foreground window before paste: %s.",
            exc.__class__.__name__,
        )
        return False
