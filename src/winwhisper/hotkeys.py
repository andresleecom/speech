from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

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
    # Numeric keypad keys (conflict-free hotkey candidates). VK_ADD etc. are the
    # same regardless of Num Lock.
    "numpad_plus": 0x6B,
    "num_plus": 0x6B,
    "kp_plus": 0x6B,
    "add": 0x6B,
    "numpad_minus": 0x6D,
    "num_minus": 0x6D,
    "subtract": 0x6D,
    "numpad_multiply": 0x6A,
    "num_multiply": 0x6A,
    "multiply": 0x6A,
    "numpad_divide": 0x6F,
    "num_divide": 0x6F,
    "divide": 0x6F,
    "numpad_decimal": 0x6E,
    "numpad0": 0x60,
    "numpad1": 0x61,
    "numpad2": 0x62,
    "numpad3": 0x63,
    "numpad4": 0x64,
    "numpad5": 0x65,
    "numpad6": 0x66,
    "numpad7": 0x67,
    "numpad8": 0x68,
    "numpad9": 0x69,
    # Main-keyboard OEM keys.
    "plus": 0xBB,  # VK_OEM_PLUS (the '+' key, any layout)
    "minus": 0xBD,  # VK_OEM_MINUS
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
        # Windows RegisterHotKey bindings: (id, fsModifiers, vk, action, combo).
        self._bindings: list[tuple[int, int, int, str, str]] = []
        # Listener-backend bindings: (modifiers, trigger name, action, combo).
        self._name_bindings: list[tuple[frozenset[str], str, str, str]] = []
        hotkey_id = 1
        for setting_key, action in _ACTIONS.items():
            combo = hotkey_map.get(setting_key)
            if not combo:
                continue
            try:
                modifiers, trigger = parse_combo(combo)
            except ValueError:
                self._logger.warning("Ignoring invalid hotkey combo for %s.", setting_key)
                continue
            self._name_bindings.append((modifiers, trigger, action, combo))
            try:
                fs_modifiers, vk = combo_to_hotkey(combo)
            except ValueError:
                if os.name == "nt":
                    self._logger.warning(
                        "Ignoring unsupported hotkey combo for %s.", setting_key
                    )
                continue
            self._bindings.append((hotkey_id, fs_modifiers, vk, action, combo))
            hotkey_id += 1

        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._started = threading.Event()
        self._stop_requested = False
        self._backend: _PynputHotkeyBackend | None = None
        self.accessibility_missing = False

    def start(self) -> None:
        if os.name == "nt":
            if self._thread is not None:
                return
            self._started.clear()
            self._stop_requested = False
            self._thread = threading.Thread(
                target=self._run,
                name="winwhisper-hotkeys",
                daemon=True,
            )
            self._thread.start()
            return

        # macOS and Linux: listener-based backend. On macOS this requires the
        # Accessibility permission; on Linux it requires X11 (Wayland needs
        # compositor-specific portals and is not supported yet).
        if self._backend is not None:
            return
        if not _macos_accessibility_trusted(prompt=True):
            # The listener starts fine without the permission but receives no
            # events, which looks like "hotkeys silently do nothing". Surface
            # it: the prompt above opens the System Settings flow.
            self.accessibility_missing = True
            self._logger.warning(
                "Accessibility permission is not granted; global hotkeys will "
                "not work until Speech is enabled under System Settings > "
                "Privacy & Security > Accessibility and the app is relaunched."
            )
        try:
            backend = _PynputHotkeyBackend(
                self._name_bindings,
                self._dispatch,
                self._logger,
            )
            backend.start()
        except Exception:
            self._logger.exception(
                "Global hotkeys are unavailable on this system; "
                "use the tray menu to start and stop recording."
            )
            return
        self._backend = backend
        for _modifiers, _trigger, _action, combo in self._name_bindings:
            self._logger.info("Registered global hotkey %s (listener backend).", combo)

    def stop(self) -> None:
        backend = self._backend
        if backend is not None:
            self._backend = None
            try:
                backend.stop()
            except Exception:
                self._logger.warning("Hotkey listener did not stop cleanly.")

        thread = self._thread
        if thread is None:
            return
        self._stop_requested = True
        self._started.wait(1.0)
        thread_id = self._thread_id
        if thread_id is not None:
            try:
                import ctypes
                from ctypes import wintypes

                # Private handle: never mutate the process-wide ctypes.windll
                # cache, whose function objects are shared with other modules.
                user32 = ctypes.WinDLL("user32", use_last_error=True)
                user32.PostThreadMessageW.argtypes = [
                    wintypes.DWORD,
                    wintypes.UINT,
                    wintypes.WPARAM,
                    wintypes.LPARAM,
                ]
                user32.PostThreadMessageW.restype = wintypes.BOOL
                if not user32.PostThreadMessageW(thread_id, _WM_QUIT, 0, 0):
                    self._logger.warning("Could not signal hotkey thread to stop.")
            except Exception:
                self._logger.warning("Could not signal hotkey thread to stop.")
        thread.join(2.0)
        self._thread = None
        self._thread_id = None

    # Give up after this many unexpected message-loop crashes in one session.
    _MAX_LOOP_RESTARTS = 10

    def _run(self) -> None:
        import ctypes
        from ctypes import wintypes

        # Use private library handles. ctypes.windll caches one function object
        # per symbol for the whole process, so modules that set their own
        # argtypes on e.g. windll.user32.GetMessageW (the native overlay does,
        # with its own MSG struct) would clobber ours mid-session: this thread's
        # next GetMessageW call then raised ArgumentError, silently killing the
        # loop and unregistering every hotkey after the first dictation.
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
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
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        self._thread_id = int(kernel32.GetCurrentThreadId())

        # Force this thread's message queue to exist now, so a WM_QUIT posted by
        # stop() before the GetMessageW loop starts cannot be dropped.
        primer = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(primer), None, 0, 0, 0)  # PM_NOREMOVE

        restarts = 0
        while True:
            registered: list[tuple[int, str]] = []
            for hotkey_id, fs_modifiers, vk, action, combo in self._bindings:
                if user32.RegisterHotKey(
                    None, hotkey_id, fs_modifiers | _MOD_NOREPEAT, vk
                ):
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

            quit_received = False
            try:
                message = wintypes.MSG()
                while True:
                    result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                    if result in (0, -1):  # WM_QUIT or error
                        quit_received = True
                        break
                    if message.message == _WM_HOTKEY:
                        fired_id = int(message.wParam)
                        action = next(
                            (a for i, a in registered if i == fired_id), None
                        )
                        if action is not None:
                            self._dispatch(action)
            except Exception:
                self._logger.exception(
                    "Hotkey message loop crashed; re-registering hotkeys."
                )
            finally:
                for hotkey_id, _action in registered:
                    try:
                        user32.UnregisterHotKey(None, hotkey_id)
                    except Exception:
                        pass

            if quit_received or self._stop_requested:
                return
            # Unexpected crash: keep global hotkeys alive rather than dying
            # silently, but never spin forever on a persistent failure.
            restarts += 1
            if restarts > self._MAX_LOOP_RESTARTS:
                self._logger.error(
                    "Hotkey message loop crashed %d times; giving up.", restarts
                )
                return

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

    # RegisterHotKey needs no modifier/trigger state to reset; the listener
    # backend does (missed key-ups and synthetic paste can poison tracking).
    def reset_state(self) -> None:
        backend = self._backend
        if backend is not None:
            backend.reset_state()

    def reset_trigger_state(self) -> None:
        backend = self._backend
        if backend is not None:
            backend.reset_trigger_state()


def _macos_accessibility_trusted(prompt: bool) -> bool:
    """True unless this is macOS and the Accessibility permission is missing.

    With ``prompt=True`` macOS shows its own dialog that deep-links into
    System Settings the first time. Returns True on other platforms or when
    the check itself is unavailable, so callers only warn on a confirmed miss.
    """
    if sys.platform != "darwin":
        return True
    try:
        from ApplicationServices import (
            AXIsProcessTrusted,
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )

        if AXIsProcessTrusted():
            return True
        if prompt:
            AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
        return False
    except Exception:
        return True


# Ignore a second matched action this soon (start+stop double-fire).
_ACTION_DEBOUNCE_SECONDS = 0.35


def normalize_char_key(char: str) -> str:
    """Normalize a character key event to a trigger name.

    Ctrl+letter arrives as a control character (\\x01-\\x1a) on some
    platforms; map it back to the letter so combos keep matching.
    """
    code = ord(char[0])
    if 1 <= code <= 26:
        return chr(code + 96)
    return char.lower()


class _PynputHotkeyBackend:
    """Listener-based hotkey matching for macOS and Linux (X11).

    Windows uses RegisterHotKey instead (see HotkeyManager). This backend
    tracks modifier state across press/release events and matches trigger
    keys by name, with the hard-won guards from the old Windows listener:
    handlers never raise (pynput kills the listener on an exception), synthetic
    paste keystrokes are ignored while suppressed, key-repeat is filtered, and
    trigger state is dropped after each action so a missed key-up cannot block
    the next take.
    """

    def __init__(
        self,
        bindings: list[tuple[frozenset[str], str, str, str]],
        dispatch: Callable[[str], None],
        logger: Any,
    ) -> None:
        self._bindings = [(m, t, a) for m, t, a, _combo in bindings]
        self._dispatch = dispatch
        self._logger = logger
        self._listener: Any | None = None
        self._state_lock = threading.Lock()
        self._pressed_modifiers: set[str] = set()
        self._down_triggers: set[str] = set()
        self._last_action_at: dict[str, float] = {}

    def start(self) -> None:
        from pynput import keyboard

        self.reset_state()
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.start()

    def stop(self) -> None:
        listener = self._listener
        self._listener = None
        if listener is not None:
            listener.stop()
        self.reset_state()

    def reset_state(self) -> None:
        with self._state_lock:
            self._pressed_modifiers.clear()
            self._down_triggers.clear()

    def reset_trigger_state(self) -> None:
        with self._state_lock:
            self._down_triggers.clear()

    def _on_press(self, key: Any) -> None:
        try:
            self._on_press_impl(key)
        except Exception:
            self._logger.exception("Hotkey on_press handler failed; listener kept alive.")

    def _on_release(self, key: Any) -> None:
        try:
            self._on_release_impl(key)
        except Exception:
            self._logger.exception("Hotkey on_release handler failed; listener kept alive.")

    def _on_press_impl(self, key: Any) -> None:
        if listener_is_suppressed():
            return

        kind, name = self._describe(key)
        now = time.monotonic()
        with self._state_lock:
            if kind == "mod":
                self._pressed_modifiers.add(name)
                # A modifier edge ends the previous chord; recovers missed key-ups.
                self._down_triggers.clear()
                return
            if name in self._down_triggers:
                return  # OS key-repeat while held
            self._down_triggers.add(name)
            pressed_modifiers = set(self._pressed_modifiers)
            last_action_at = dict(self._last_action_at)

        for modifiers, trigger, action in self._bindings:
            if trigger != name or modifiers != pressed_modifiers:
                continue
            if now - last_action_at.get(action, 0.0) < _ACTION_DEBOUNCE_SECONDS:
                return
            with self._state_lock:
                self._last_action_at[action] = now
            self._dispatch(action)
            return

    def _on_release_impl(self, key: Any) -> None:
        kind, name = self._describe(key)
        with self._state_lock:
            if kind == "mod":
                self._pressed_modifiers.discard(name)
                self._down_triggers.clear()
            else:
                self._down_triggers.discard(name)

    def _describe(self, key: Any) -> tuple[str, str]:
        """Classify an event key as ("mod", alias) or ("key", trigger name)."""
        from pynput import keyboard

        if isinstance(key, keyboard.Key):
            alias = _MODIFIER_ALIASES.get(key.name)
            if alias is not None:
                return "mod", alias
            return "key", key.name
        char = getattr(key, "char", None)
        if char:
            return "key", normalize_char_key(char)
        vk = getattr(key, "vk", None)
        return "key", f"vk{vk}"
