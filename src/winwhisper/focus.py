from __future__ import annotations

import ctypes
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .logger import get_logger

WindowHandle = int


@dataclass(frozen=True)
class ScreenPoint:
    x: int
    y: int


def get_foreground_window() -> WindowHandle | None:
    if sys.platform.startswith("linux"):
        return _x11_active_window()

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
    if sys.platform.startswith("linux"):
        # X11 has no portable caret query, so anchor the orb at the pointer.
        return _x11_pointer_position()

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
    if sys.platform.startswith("linux"):
        return _x11_window_process_name(hwnd)

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
    if sys.platform.startswith("linux"):
        return _x11_activate_window(hwnd)

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


# --- Linux/X11 focus helpers -------------------------------------------------
# Best-effort: every helper no-ops (returns None) on pure Wayland without
# XWayland, when DISPLAY is unset, or when python-xlib is unavailable. The app
# then behaves as it did before Linux window detection existed.


def _x11_display() -> Any | None:
    if not os.environ.get("DISPLAY"):
        return None
    try:
        from Xlib import display as xdisplay
    except Exception:
        return None
    try:
        return xdisplay.Display()
    except Exception:
        return None


def _x11_active_window() -> WindowHandle | None:
    disp = _x11_display()
    if disp is None:
        return None
    try:
        from Xlib import X

        root = disp.screen().root
        atom = disp.intern_atom("_NET_ACTIVE_WINDOW")
        prop = root.get_full_property(atom, X.AnyPropertyType)
        if prop is None or not getattr(prop, "value", None):
            return None
        return int(prop.value[0]) or None
    except Exception:
        return None
    finally:
        try:
            disp.close()
        except Exception:
            pass


def _x11_pointer_position() -> ScreenPoint | None:
    disp = _x11_display()
    if disp is None:
        return None
    try:
        data = disp.screen().root.query_pointer()
        return ScreenPoint(int(data.root_x), int(data.root_y))
    except Exception:
        return None
    finally:
        try:
            disp.close()
        except Exception:
            pass


def _x11_window_process_name(hwnd: WindowHandle | None) -> str | None:
    if hwnd is None:
        return None
    disp = _x11_display()
    if disp is None:
        return None
    try:
        from Xlib import X

        atom = disp.intern_atom("_NET_WM_PID")
        win = disp.create_resource_object("window", hwnd)
        prop = win.get_full_property(atom, X.AnyPropertyType)
        if prop is None or not getattr(prop, "value", None):
            return None
        pid = int(prop.value[0])
    except Exception:
        return None
    finally:
        try:
            disp.close()
        except Exception:
            pass

    return _process_name_for_pid(pid)


def _x11_activate_window(hwnd: WindowHandle | None) -> bool:
    """Raise and focus the target window before pasting (EWMH).

    The recording orb is an override-redirect window and should not steal
    focus, but some window managers still shift the active window while it is
    up. Re-activating the caller's original window makes the synthetic paste
    land where the user was typing instead of nowhere.
    """
    if hwnd is None:
        return False
    disp = _x11_display()
    if disp is None:
        return False
    try:
        from Xlib import X, protocol

        root = disp.screen().root
        win = disp.create_resource_object("window", hwnd)
        net_active = disp.intern_atom("_NET_ACTIVE_WINDOW")
        active_prop = root.get_full_property(net_active, X.AnyPropertyType)
        active_value = getattr(active_prop, "value", None)
        current_active = int(active_value[0]) if active_value else 0
        event = protocol.event.ClientMessage(
            window=win,
            client_type=net_active,
            # source indication 1 = "from an application", per EWMH.
            data=(32, [1, X.CurrentTime, current_active, 0, 0]),
        )
        mask = X.SubstructureRedirectMask | X.SubstructureNotifyMask
        root.send_event(event, event_mask=mask)
        disp.flush()
        # Window managers may reject activation requests. Confirm the target
        # became active before allowing the caller to synthesize a paste.
        for attempt in range(6):
            disp.sync()
            active_prop = root.get_full_property(net_active, X.AnyPropertyType)
            active_value = getattr(active_prop, "value", None)
            if active_value and int(active_value[0]) == hwnd:
                return True
            if attempt < 5:
                time.sleep(0.025)
        return False
    except Exception:
        return False
    finally:
        try:
            disp.close()
        except Exception:
            pass


def _process_name_for_pid(pid: int) -> str | None:
    if pid <= 0:
        return None
    # Prefer the executable's real name; /proc/<pid>/comm is truncated to 15
    # bytes (e.g. "gnome-terminal-"), which breaks exact-match lookups.
    try:
        return Path(os.readlink(f"/proc/{pid}/exe")).name
    except OSError:
        pass
    try:
        name = Path(f"/proc/{pid}/comm").read_text(encoding="utf-8").strip()
        return name or None
    except OSError:
        return None
