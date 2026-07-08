from __future__ import annotations

import ctypes
import queue
import threading
from collections.abc import Callable
from ctypes import wintypes
from typing import Any

from .branding import APP_NAME
from .focus import ScreenPoint
from .overlay import (
    OverlayCommand,
    OverlayState,
    _HEIGHT,
    _WIDTH,
    dragged_overlay_position,
    is_stop_button_point,
    position_near_anchor,
    render_orb_frame,
)

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32
LRESULT = getattr(wintypes, "LRESULT", wintypes.LPARAM)
HBITMAP = getattr(wintypes, "HBITMAP", wintypes.HANDLE)
HBRUSH = getattr(wintypes, "HBRUSH", wintypes.HANDLE)
HCURSOR = getattr(wintypes, "HCURSOR", wintypes.HANDLE)
HGDIOBJ = getattr(wintypes, "HGDIOBJ", wintypes.HANDLE)
HICON = getattr(wintypes, "HICON", wintypes.HANDLE)
UINT_PTR = getattr(wintypes, "UINT_PTR", wintypes.WPARAM)

WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008

SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
HWND_TOPMOST = wintypes.HWND(-1)

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_TIMER = 0x0113
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSEMOVE = 0x0200
MK_LBUTTON = 0x0001

TIMER_COMMANDS = 1
TIMER_ANIMATION = 2
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
DIB_RGB_COLORS = 0
BI_RGB = 0


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]


WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", HICON),
        ("hCursor", HCURSOR),
        ("hbrBackground", HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
user32.RegisterClassW.restype = wintypes.ATOM
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.DefWindowProcW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.DefWindowProcW.restype = LRESULT
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.GetMessageW.argtypes = [
    ctypes.POINTER(MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
]
user32.GetMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
user32.SetTimer.argtypes = [wintypes.HWND, UINT_PTR, wintypes.UINT, wintypes.LPVOID]
user32.KillTimer.argtypes = [wintypes.HWND, UINT_PTR]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.SetCapture.argtypes = [wintypes.HWND]
user32.ReleaseCapture.argtypes = []
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND,
    wintypes.HDC,
    ctypes.POINTER(POINT),
    ctypes.POINTER(SIZE),
    wintypes.HDC,
    ctypes.POINTER(POINT),
    wintypes.COLORREF,
    ctypes.POINTER(BLENDFUNCTION),
    wintypes.DWORD,
]
user32.UpdateLayeredWindow.restype = wintypes.BOOL

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.SelectObject.argtypes = [wintypes.HDC, HGDIOBJ]
gdi32.SelectObject.restype = HGDIOBJ
gdi32.DeleteObject.argtypes = [HGDIOBJ]
gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC,
    ctypes.POINTER(BITMAPINFO),
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p),
    wintypes.HANDLE,
    wintypes.DWORD,
]
gdi32.CreateDIBSection.restype = HBITMAP

kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


def run_native_overlay(
    commands: queue.Queue[OverlayCommand],
    on_stop: Callable[[], None],
    level_provider: Callable[[], float],
    logger: Any,
) -> None:
    NativeOverlayWindow(commands, on_stop, level_provider, logger).run()


def rgba_to_bgra_premultiplied(image: Any) -> bytes:
    rgba = image.convert("RGBA").tobytes()
    output = bytearray(len(rgba))
    for index in range(0, len(rgba), 4):
        red = rgba[index]
        green = rgba[index + 1]
        blue = rgba[index + 2]
        alpha = rgba[index + 3]
        output[index] = blue * alpha // 255
        output[index + 1] = green * alpha // 255
        output[index + 2] = red * alpha // 255
        output[index + 3] = alpha
    return bytes(output)


class NativeOverlayWindow:
    def __init__(
        self,
        commands: queue.Queue[OverlayCommand],
        on_stop: Callable[[], None],
        level_provider: Callable[[], float],
        logger: Any,
    ) -> None:
        self._commands = commands
        self._on_stop = on_stop
        self._level_provider = level_provider
        self._logger = logger
        self._state: OverlayState = "hidden"
        self._phase = 0
        self._x = 0
        self._y = 0
        self._drag_origin: ScreenPoint | None = None
        self._drag_press: ScreenPoint | None = None
        self._hwnd: wintypes.HWND | None = None
        self._class_name = f"SpeechOverlay{id(self)}"
        self._wndproc = WNDPROC(self._window_proc)

    def run(self) -> None:
        hinstance = kernel32.GetModuleHandleW(None)
        window_class = WNDCLASS()
        window_class.lpfnWndProc = self._wndproc
        window_class.hInstance = hinstance
        window_class.lpszClassName = self._class_name
        atom = user32.RegisterClassW(ctypes.byref(window_class))
        if not atom:
            raise ctypes.WinError()

        self._hwnd = user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
            self._class_name,
            f"{APP_NAME} Recording Overlay",
            WS_POPUP,
            0,
            0,
            _WIDTH,
            _HEIGHT,
            None,
            None,
            hinstance,
            None,
        )
        if not self._hwnd:
            raise ctypes.WinError()

        user32.SetTimer(self._hwnd, TIMER_COMMANDS, 50, None)
        user32.SetTimer(self._hwnd, TIMER_ANIMATION, 75, None)

        message = MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))

    def _window_proc(
        self,
        hwnd: wintypes.HWND,
        message: int,
        wparam: int,
        lparam: int,
    ) -> int:
        if message == WM_TIMER:
            if int(wparam) == TIMER_COMMANDS:
                self._pump_commands()
            elif int(wparam) == TIMER_ANIMATION:
                self._animate()
            return 0
        if message == WM_LBUTTONDOWN:
            self._handle_mouse_down(hwnd, lparam)
            return 0
        if message == WM_MOUSEMOVE:
            self._handle_mouse_move(wparam)
            return 0
        if message == WM_LBUTTONUP:
            self._end_drag()
            return 0
        if message == WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if message == WM_DESTROY:
            user32.KillTimer(hwnd, TIMER_COMMANDS)
            user32.KillTimer(hwnd, TIMER_ANIMATION)
            user32.PostQuitMessage(0)
            return 0
        return int(user32.DefWindowProcW(hwnd, message, wparam, lparam))

    def _pump_commands(self) -> None:
        hwnd = self._require_hwnd()
        while True:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                break

            if command.name == "show":
                self._position(command.anchor)
                self._state = "recording"
                self._render()
                user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
            elif command.name == "hide":
                self._state = "hidden"
                user32.ShowWindow(hwnd, SW_HIDE)
            elif command.name == "transcribing":
                self._state = "transcribing"
                self._render()
                user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
            elif command.name == "stop":
                user32.DestroyWindow(hwnd)
                break

    def _animate(self) -> None:
        if self._state == "hidden":
            return
        self._phase += 1
        self._render()

    def _handle_mouse_down(self, hwnd: wintypes.HWND, lparam: int) -> None:
        x = _loword_signed(lparam)
        y = _hiword_signed(lparam)
        if is_stop_button_point(x, y):
            self._request_stop()
            return

        point = _cursor_pos()
        self._drag_origin = ScreenPoint(self._x, self._y)
        self._drag_press = ScreenPoint(point.x, point.y)
        user32.SetCapture(hwnd)

    def _handle_mouse_move(self, wparam: int) -> None:
        if not (int(wparam) & MK_LBUTTON):
            return
        if self._drag_origin is None or self._drag_press is None:
            return

        point = _cursor_pos()
        x, y = dragged_overlay_position(
            self._drag_origin,
            self._drag_press,
            ScreenPoint(point.x, point.y),
            user32.GetSystemMetrics(0),
            user32.GetSystemMetrics(1),
        )
        self._move(x, y)

    def _end_drag(self) -> None:
        self._drag_origin = None
        self._drag_press = None
        user32.ReleaseCapture()

    def _request_stop(self) -> None:
        self._state = "transcribing"
        self._render()
        threading.Thread(
            target=self._on_stop,
            name="winwhisper-overlay-stop",
            daemon=True,
        ).start()

    def _position(self, anchor: ScreenPoint | None) -> None:
        self._x, self._y = position_near_anchor(
            anchor,
            user32.GetSystemMetrics(0),
            user32.GetSystemMetrics(1),
        )

    def _move(self, x: int, y: int) -> None:
        hwnd = self._require_hwnd()
        self._x = x
        self._y = y
        user32.SetWindowPos(
            hwnd,
            HWND_TOPMOST,
            self._x,
            self._y,
            0,
            0,
            SWP_NOSIZE | SWP_NOACTIVATE,
        )

    def _render(self) -> None:
        image = render_orb_frame(self._state, self._current_level(), self._phase)
        bgra = rgba_to_bgra_premultiplied(image)
        self._update_layered_window(bgra)

    def _update_layered_window(self, bgra: bytes) -> None:
        hwnd = self._require_hwnd()
        screen_dc = user32.GetDC(None)
        if not screen_dc:
            raise ctypes.WinError()
        memory_dc = gdi32.CreateCompatibleDC(screen_dc)
        if not memory_dc:
            user32.ReleaseDC(None, screen_dc)
            raise ctypes.WinError()

        bits = ctypes.c_void_p()
        bitmap_info = BITMAPINFO()
        bitmap_info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bitmap_info.bmiHeader.biWidth = _WIDTH
        bitmap_info.bmiHeader.biHeight = -_HEIGHT
        bitmap_info.bmiHeader.biPlanes = 1
        bitmap_info.bmiHeader.biBitCount = 32
        bitmap_info.bmiHeader.biCompression = BI_RGB
        bitmap = gdi32.CreateDIBSection(
            screen_dc,
            ctypes.byref(bitmap_info),
            DIB_RGB_COLORS,
            ctypes.byref(bits),
            None,
            0,
        )
        if not bitmap:
            gdi32.DeleteDC(memory_dc)
            user32.ReleaseDC(None, screen_dc)
            raise ctypes.WinError()

        old_bitmap = gdi32.SelectObject(memory_dc, bitmap)
        try:
            ctypes.memmove(bits, bgra, len(bgra))
            location = POINT(self._x, self._y)
            size = SIZE(_WIDTH, _HEIGHT)
            source = POINT(0, 0)
            blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
            if not user32.UpdateLayeredWindow(
                hwnd,
                screen_dc,
                ctypes.byref(location),
                ctypes.byref(size),
                memory_dc,
                ctypes.byref(source),
                0,
                ctypes.byref(blend),
                ULW_ALPHA,
            ):
                raise ctypes.WinError()
        finally:
            gdi32.SelectObject(memory_dc, old_bitmap)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(memory_dc)
            user32.ReleaseDC(None, screen_dc)

    def _current_level(self) -> float:
        try:
            return min(1.0, max(0.0, float(self._level_provider())))
        except Exception as exc:
            self._logger.warning(
                "Overlay level provider failed with %s.",
                exc.__class__.__name__,
            )
            return 0.0

    def _require_hwnd(self) -> wintypes.HWND:
        if self._hwnd is None:
            raise RuntimeError("Native overlay window has not been created.")
        return self._hwnd


def _cursor_pos() -> POINT:
    point = POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        raise ctypes.WinError()
    return point


def _loword_signed(value: int) -> int:
    word = value & 0xFFFF
    return word - 0x10000 if word & 0x8000 else word


def _hiword_signed(value: int) -> int:
    word = (value >> 16) & 0xFFFF
    return word - 0x10000 if word & 0x8000 else word
