from __future__ import annotations

import os
import threading
from collections.abc import Callable, Mapping

from .logger import get_logger

_ACTIONS = {
    "toggle_recording": "toggle",
    "force_english": "force_en",
    "force_spanish": "force_es",
}

_MODIFIER_ALIASES = {
    "ctrl": "ctrl",
    "ctrl_l": "ctrl",
    "ctrl_r": "ctrl",
    "alt": "alt",
    "alt_l": "alt",
    "alt_r": "alt",
    "alt_gr": "alt",
    "shift": "shift",
    "shift_l": "shift",
    "shift_r": "shift",
    "cmd": "cmd",
    "cmd_l": "cmd",
    "cmd_r": "cmd",
}

# RegisterHotKey modifier flags (winuser.h).
_MOD_ALT = 0x0001
_MOD_CONTROL = 0x0002
_MOD_SHIFT = 0x0004
_MOD_WIN = 0x0008
_MOD_NOREPEAT = 0x4000

_MODIFIER_TO_WIN = {
    "alt": _MOD_ALT,
    "ctrl": _MOD_CONTROL,
    "shift": _MOD_SHIFT,
    "cmd": _MOD_WIN,
}

# Virtual-key codes for named trigger keys we support beyond letters/digits.
_NAMED_TRIGGER_VK = {
    "space": 0x20,
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "esc": 0x1B,
    "escape": 0x1B,
    "backspace": 0x08,
    "delete": 0x2E,
    "del": 0x2E,
    "insert": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "pause": 0x13,
    "scroll_lock": 0x91,
    "print_screen": 0x2C,
    "caps_lock": 0x14,
    "menu": 0x5D,
}

_WM_HOTKEY = 0x0312
_WM_QUIT = 0x0012

# Kept for backwards compatibility with the paste path. The native RegisterHotKey
# engine never sees synthetic keystrokes as hotkeys, so suppression is a no-op,
# but callers (inserter.py) still toggle it.
_suppress_events = False
_suppress_lock = threading.Lock()


def set_listener_suppressed(suppressed: bool) -> None:
    global _suppress_events
    with _suppress_lock:
        _suppress_events = suppressed


def listener_is_suppressed() -> bool:
    with _suppress_lock:
        return _suppress_events


def normalize_combo(combo: str) -> str:
    """Wrap bare named keys in brackets (e.g. "space" -> "<space>")."""
    parts = []
    for part in combo.split("+"):
        token = part.strip()
        if len(token) > 1 and not (token.startswith("<") and token.endswith(">")):
            token = f"<{token}>"
        parts.append(token)
    return "+".join(parts)


def parse_combo(combo: str) -> tuple[frozenset[str], str]:
    """Split a combo string into (required modifiers, trigger key name).

    Trigger names are lowercase: a named key ("space", "f4") or a single
    character ("e").
    """
    modifiers: set[str] = set()
    trigger: str | None = None
    for part in normalize_combo(combo).split("+"):
        token = part.strip()
        if token.startswith("<") and token.endswith(">"):
            name = token[1:-1].lower()
        else:
            name = token.lower()
        if name in _MODIFIER_ALIASES:
            modifiers.add(_MODIFIER_ALIASES[name])
        elif trigger is None:
            trigger = name
        else:
            raise ValueError(f"Hotkey combo has multiple trigger keys: {combo!r}")
    if trigger is None:
        raise ValueError(f"Hotkey combo has no trigger key: {combo!r}")
    return frozenset(modifiers), trigger


def trigger_to_vk(trigger: str) -> int:
    """Map a trigger key name to a Windows virtual-key code."""
    name = trigger.lower()
    if len(name) == 1 and name.isascii():
        if name.isalpha():
            return ord(name.upper())
        if name.isdigit():
            return ord(name)
    if name in _NAMED_TRIGGER_VK:
        return _NAMED_TRIGGER_VK[name]
    if name.startswith("f") and name[1:].isdigit():
        number = int(name[1:])
        if 1 <= number <= 24:
            return 0x70 + (number - 1)  # VK_F1 == 0x70
    raise ValueError(f"Unsupported hotkey trigger key: {trigger!r}")


def combo_to_hotkey(combo: str) -> tuple[int, int]:
    """Convert a combo string to (fsModifiers, virtual-key) for RegisterHotKey."""
    modifiers, trigger = parse_combo(combo)
    fs_modifiers = 0
    for modifier in modifiers:
        flag = _MODIFIER_TO_WIN.get(modifier)
        if flag is None:
            raise ValueError(f"Unsupported hotkey modifier {modifier!r} in {combo!r}")
        fs_modifiers |= flag
    return fs_modifiers, trigger_to_vk(trigger)


class HotkeyManager:
    """Global hotkey dispatcher built on the Win32 ``RegisterHotKey`` API.

    An earlier implementation used a pynput low-level keyboard hook. On some
    machines Windows silently tears that hook down after the app opens its own
    overlay window (a startup timing race), so the hotkey fired exactly once and
    then went dead - re-installing the hook did not help because fresh hooks were
    torn down too. ``RegisterHotKey`` is not a hook: Windows posts ``WM_HOTKEY``
    to a dedicated message-loop thread, which is immune to that failure and needs
    none of the modifier tracking, debounce, or suppression the hook required.
    """

    def __init__(
        self,
        hotkey_map: Mapping[str, str],
        on_hotkey: Callable[[str], None],
    ) -> None:
        self._on_hotkey = on_hotkey
        self._logger = get_logger(__name__)
        self._bindings: list[tuple[int, int, int, str, str]] = []
        hotkey_id = 1
        for setting_key, action in _ACTIONS.items():
            combo = hotkey_map.get(setting_key)
            if not combo:
                continue
            try:
                fs_modifiers, vk = combo_to_hotkey(combo)
            except ValueError:
                self._logger.warning("Ignoring invalid hotkey combo for %s.", setting_key)
                continue
            self._bindings.append((hotkey_id, fs_modifiers, vk, action, combo))
            hotkey_id += 1

        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._started = threading.Event()

    def start(self) -> None:
        if os.name != "nt":
            self._logger.info("Global hotkeys require Windows; hotkey listener disabled.")
            return
        if self._thread is not None:
            return
        self._started.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="winwhisper-hotkeys",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return
        self._started.wait(1.0)
        thread_id = self._thread_id
        if thread_id is not None:
            try:
                import ctypes
                from ctypes import wintypes

                post = ctypes.windll.user32.PostThreadMessageW
                post.argtypes = [
                    wintypes.DWORD,
                    wintypes.UINT,
                    wintypes.WPARAM,
                    wintypes.LPARAM,
                ]
                post.restype = wintypes.BOOL
                if not post(thread_id, _WM_QUIT, 0, 0):
                    self._logger.warning("Could not signal hotkey thread to stop.")
            except Exception:
                self._logger.warning("Could not signal hotkey thread to stop.")
        thread.join(2.0)
        self._thread = None
        self._thread_id = None

    def _run(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.RegisterHotKey.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            wintypes.UINT,
            wintypes.UINT,
        ]
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        ]
        user32.GetMessageW.restype = ctypes.c_int
        user32.PeekMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
            wintypes.UINT,
        ]
        user32.PeekMessageW.restype = wintypes.BOOL
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        self._thread_id = int(kernel32.GetCurrentThreadId())

        # Force this thread's message queue to exist now, so a WM_QUIT posted by
        # stop() before the GetMessageW loop starts cannot be dropped.
        primer = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(primer), None, 0, 0, 0)  # PM_NOREMOVE

        registered: list[tuple[int, str]] = []
        for hotkey_id, fs_modifiers, vk, action, combo in self._bindings:
            if user32.RegisterHotKey(None, hotkey_id, fs_modifiers | _MOD_NOREPEAT, vk):
                registered.append((hotkey_id, action))
                self._logger.info("Registered global hotkey %s.", combo)
            else:
                self._logger.warning(
                    "Could not register hotkey %s; it may already be in use by "
                    "another application. Choose a different combo in settings.",
                    combo,
                )

        self._started.set()
        if not registered:
            self._logger.warning("No global hotkeys were registered.")

        try:
            message = wintypes.MSG()
            while True:
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result in (0, -1):  # WM_QUIT or error
                    break
                if message.message == _WM_HOTKEY:
                    fired_id = int(message.wParam)
                    action = next((a for i, a in registered if i == fired_id), None)
                    if action is not None:
                        self._dispatch(action)
        finally:
            for hotkey_id, _action in registered:
                try:
                    user32.UnregisterHotKey(None, hotkey_id)
                except Exception:
                    pass

    def _dispatch(self, action: str) -> None:
        self._logger.info("Hotkey matched action=%s.", action)
        threading.Thread(
            target=self._run_callback,
            args=(action,),
            name="winwhisper-hotkey-dispatch",
            daemon=True,
        ).start()

    def _run_callback(self, action: str) -> None:
        try:
            self._on_hotkey(action)
        except Exception:
            self._logger.exception("Hotkey callback failed for action %s.", action)

    # Retained as no-ops so callers written for the old hook engine keep working;
    # RegisterHotKey needs no modifier/trigger state to reset.
    def reset_state(self) -> None:
        pass

    def reset_trigger_state(self) -> None:
        pass
