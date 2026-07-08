from __future__ import annotations

import ctypes
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .logger import get_logger

WindowHandle = int


@dataclass(frozen=True)
class ScreenPoint:
    x: int
    y: int


def get_foreground_window() -> WindowHandle | None:
    if os.name != "nt":
        return None

    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
    except Exception as exc:
        get_logger(__name__).warning(
            "Could not capture foreground window: %s.",
            exc.__class__.__name__,
        )
        return None

    return int(hwnd) or None


def get_cursor_anchor(hwnd: WindowHandle | None = None) -> ScreenPoint | None:
    """Best-effort caret/mouse point for overlay placement.

    Prefer the text caret when it is near the mouse (same interaction),
    otherwise use the mouse. Multi-monitor setups often report a caret on a
    different display than the one the user is looking at; in that case the
    mouse is the reliable signal.
    """
    if os.name != "nt":
        return None

    mouse = _get_mouse_position()
    caret = _get_caret_position(hwnd)
    if mouse is None and caret is None:
        return _fallback_screen_point()
    if mouse is None:
        return caret
    if caret is None:
        return mouse

    # Caret far from the mouse is usually stale or on another monitor.
    if abs(caret.x - mouse.x) <= 900 and abs(caret.y - mouse.y) <= 900:
        return caret
    get_logger(__name__).info(
        "Ignoring distant caret (%s,%s); using mouse (%s,%s) for overlay.",
        caret.x,
        caret.y,
        mouse.x,
        mouse.y,
    )
    return mouse


def _fallback_screen_point() -> ScreenPoint:
    """Center of the primary work area when caret and mouse are unavailable."""
    try:
        user32 = ctypes.windll.user32
        width = int(user32.GetSystemMetrics(0)) or 800
        height = int(user32.GetSystemMetrics(1)) or 600
        return ScreenPoint(width // 2, height // 2)
    except Exception:
        return ScreenPoint(200, 200)


def get_window_process_name(hwnd: WindowHandle | None) -> str | None:
    if os.name != "nt" or hwnd is None:
        return None

    try:
        from ctypes import wintypes

        process_id = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if process_id.value == 0:
            return None

        process_handle = ctypes.windll.kernel32.OpenProcess(
            0x1000,
            False,
            process_id.value,
        )
        if not process_handle:
            return None

        try:
            buffer_size = wintypes.DWORD(1024)
            buffer = ctypes.create_unicode_buffer(buffer_size.value)
            if not ctypes.windll.kernel32.QueryFullProcessImageNameW(
                process_handle,
                0,
                buffer,
                ctypes.byref(buffer_size),
            ):
                return None
            return Path(buffer.value).name
        finally:
            ctypes.windll.kernel32.CloseHandle(process_handle)
    except Exception as exc:
        get_logger(__name__).warning(
            "Could not detect foreground process: %s.",
            exc.__class__.__name__,
        )
        return None


def restore_foreground_window(hwnd: WindowHandle | None) -> bool:
    if os.name != "nt" or hwnd is None:
        return False

    try:
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


def _get_caret_position(hwnd: WindowHandle | None) -> ScreenPoint | None:
    if hwnd is None:
        return None

    try:
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        class GUITHREADINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("hwndActive", wintypes.HWND),
                ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND),
                ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND),
                ("hwndCaret", wintypes.HWND),
                ("rcCaret", RECT),
            ]

        thread_id = ctypes.windll.user32.GetWindowThreadProcessId(hwnd, None)
        if not thread_id:
            return None

        info = GUITHREADINFO()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)):
            return None
        if not info.hwndCaret:
            return None

        point = wintypes.POINT(info.rcCaret.left, info.rcCaret.bottom)
        if not ctypes.windll.user32.ClientToScreen(info.hwndCaret, ctypes.byref(point)):
            return None
        return ScreenPoint(int(point.x), int(point.y))
    except Exception:
        return None


def _get_mouse_position() -> ScreenPoint | None:
    try:
        from ctypes import wintypes

        point = wintypes.POINT()
        if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
            return None
        return ScreenPoint(int(point.x), int(point.y))
    except Exception:
        return None
