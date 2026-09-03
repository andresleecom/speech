from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .hotkey_actions import (
    HOTKEY_ACTIONS,
    TOGGLE_ACTION,
    TOGGLE_RELEASE_ACTION,
    is_macos_supported_trigger,
)
from .logger import get_logger
from .mouse_buttons import is_mouse_trigger, mouse_button_name

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
PUSH_TO_TALK_HOLD_SECONDS = 0.5
_PUSH_TO_TALK_POLL_SECONDS = 0.015

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
    # Single characters outside the name table (OEM punctuation, ñ, º, …)
    # resolve through the active keyboard layout.
    if len(trigger) == 1:
        vk = _vk_from_layout_character(trigger)
        if vk is not None:
            return vk
    raise ValueError(f"Unsupported hotkey trigger key: {trigger!r}")


def _installed_layouts() -> tuple[int, ...]:
    """Return installed keyboard layouts, current thread layout first.

    ``GetKeyboardLayoutList`` lists every HKL the user has installed; the
    active per-window layout can still be a different one. OEM characters and
    AltGr collisions must be resolved against the full set so a chord saved as
    ``<`` always binds the physical ISO key even when en-US is current.
    """
    if os.name != "nt":
        return ()

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    current = int(user32.GetKeyboardLayout(0))
    count = int(user32.GetKeyboardLayoutList(0, None))
    if count <= 0:
        return (current,)
    array = (wintypes.HKL * count)()
    filled = int(user32.GetKeyboardLayoutList(count, array))
    layouts = [current]
    seen = {current}
    for index in range(max(filled, 0)):
        layout = int(array[index])
        if layout not in seen:
            layouts.append(layout)
            seen.add(layout)
    return tuple(layouts)


def _vk_from_layout_character(character: str) -> int | None:
    """Map one character to a VK via VkKeyScanExW across installed layouts.

    Prefers a layout where the character is unshifted (high byte 0), otherwise
    the first layout that maps it at all.
    """
    if os.name != "nt":
        return None

    import ctypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    first_mapped: int | None = None
    for layout in _installed_layouts():
        result = int(user32.VkKeyScanExW(ord(character), layout))
        if result in (-1, 0xFFFF):
            continue
        vk = result & 0xFF
        shift_state = (result >> 8) & 0xFF
        if shift_state == 0:
            return vk
        if first_mapped is None:
            first_mapped = vk
    return first_mapped


def altgr_produces_character(vk: int) -> str | None:
    """Return the character AltGr (Ctrl+Alt) types for ``vk``, if any.

    Checks every installed layout (current first). Used to reject
    Ctrl+Alt+printable chords that any installed layout already claims for
    typing (for example AltGr+E → € on es-ES even while en-US is active).
    """
    if os.name != "nt":
        return None

    import ctypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    keystate = (ctypes.c_ubyte * 256)()
    keystate[0x11] = 0x80  # VK_CONTROL
    keystate[0x12] = 0x80  # VK_MENU (Alt)
    keystate[0xA2] = 0x80  # VK_LCONTROL
    keystate[0xA5] = 0x80  # VK_RMENU (right Alt / AltGr)
    for layout in _installed_layouts():
        buf = ctypes.create_unicode_buffer(8)
        scancode = int(user32.MapVirtualKeyExW(vk, 0, layout))
        produced = int(
            user32.ToUnicodeEx(vk, scancode, keystate, buf, len(buf), 0, layout)
        )
        character = buf.value if produced > 0 else ""
        # Clear any dead-key state ToUnicodeEx may have left behind.
        clear_state = (ctypes.c_ubyte * 256)()
        clear_buf = ctypes.create_unicode_buffer(8)
        user32.ToUnicodeEx(
            vk, scancode, clear_state, clear_buf, len(clear_buf), 0, layout
        )
        if produced > 0 and character:
            return character[0]
    return None


def character_for_virtual_key(vk: int) -> str | None:
    """Return the unshifted character a VK types on an installed layout.

    For each layout (current first), read the unshifted glyph with
    ``ToUnicodeEx`` and accept it only when ``VkKeyScanExW`` round-trips to
    the same VK. That rejects cases like en-US mapping OEM_102 to a glyph
    whose real key is a different VK (e.g. ``\\`` on 0xDC).
    """
    if os.name != "nt":
        return None

    import ctypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    empty_state = (ctypes.c_ubyte * 256)()
    for layout in _installed_layouts():
        buf = ctypes.create_unicode_buffer(8)
        scancode = int(user32.MapVirtualKeyExW(vk, 0, layout))
        produced = int(
            user32.ToUnicodeEx(
                vk, scancode, empty_state, buf, len(buf), 0, layout
            )
        )
        # Clear any dead-key state ToUnicodeEx may have left behind.
        clear_buf = ctypes.create_unicode_buffer(8)
        user32.ToUnicodeEx(
            vk, scancode, empty_state, clear_buf, len(clear_buf), 0, layout
        )
        if produced <= 0 or not buf.value:
            continue
        character = buf.value[0]
        if character.isspace() or not character.isprintable():
            continue
        scan = int(user32.VkKeyScanExW(ord(character), layout))
        if scan in (-1, 0xFFFF):
            continue
        if (scan & 0xFF) == vk:
            return character
    return None


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


def windows_modifier_state() -> set[str]:
    """Read live modifier state, for matching a mouse button against a chord.

    Windows has no keyboard listener here (RegisterHotKey handles keys), so the
    modifiers held at click time have to be queried directly.
    """
    import ctypes

    # Private handle: never mutate the process-wide ctypes.windll cache, whose
    # function objects are shared with other modules.
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short

    def is_down(vk: int) -> bool:
        return bool(user32.GetAsyncKeyState(vk) & 0x8000)

    pressed: set[str] = set()
    if is_down(0x11):  # VK_CONTROL
        pressed.add("ctrl")
    if is_down(0x12):  # VK_MENU
        pressed.add("alt")
    if is_down(0x10):  # VK_SHIFT
        pressed.add("shift")
    if is_down(0x5B) or is_down(0x5C):  # VK_LWIN / VK_RWIN
        pressed.add("cmd")
    return pressed


@dataclass(frozen=True)
class HotkeyActivationResult:
    active: tuple[str, ...]
    failed: tuple[str, ...]

    @property
    def successful(self) -> bool:
        return not self.failed


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
        self._requested_combos = tuple(
            combo
            for action in HOTKEY_ACTIONS
            if (combo := hotkey_map.get(action.setting_key))
        )
        self._rejected_combos: list[str] = []
        self._activation_result = HotkeyActivationResult(active=(), failed=())
        # Windows RegisterHotKey bindings: (id, fsModifiers, vk, action, combo).
        self._bindings: list[tuple[int, int, int, str, str]] = []
        # Listener-backend bindings: (modifiers, trigger name, action, combo).
        self._name_bindings: list[tuple[frozenset[str], str, str, str]] = []
        # Mouse bindings: (modifiers, pynput button name, action, combo).
        self._mouse_bindings: list[tuple[frozenset[str], str, str, str]] = []
        hotkey_id = 1
        for action in HOTKEY_ACTIONS:
            combo = hotkey_map.get(action.setting_key)
            if not combo:
                continue
            try:
                modifiers, trigger = parse_combo(combo)
            except ValueError:
                self._logger.warning(
                    "Ignoring invalid hotkey combo for %s.",
                    action.setting_key,
                )
                self._rejected_combos.append(combo)
                continue
            if is_mouse_trigger(trigger):
                # Mouse buttons bypass RegisterHotKey and the macOS key-trigger
                # allowlist alike; they are matched by the mouse listener.
                self._mouse_bindings.append(
                    (
                        modifiers,
                        mouse_button_name(trigger),
                        action.dispatch_action,
                        combo,
                    )
                )
                continue
            if sys.platform == "darwin" and not is_macos_supported_trigger(trigger):
                self._logger.warning(
                    "Ignoring unsupported macOS hotkey combo for %s.",
                    action.setting_key,
                )
                self._rejected_combos.append(combo)
                continue
            self._name_bindings.append(
                (modifiers, trigger, action.dispatch_action, combo)
            )
            try:
                fs_modifiers, vk = combo_to_hotkey(combo)
            except ValueError:
                if os.name == "nt":
                    self._logger.warning(
                        "Ignoring unsupported hotkey combo for %s.",
                        action.setting_key,
                    )
                    self._rejected_combos.append(combo)
                continue
            self._bindings.append(
                (
                    hotkey_id,
                    fs_modifiers,
                    vk,
                    action.dispatch_action,
                    combo,
                )
            )
            hotkey_id += 1

        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._started = threading.Event()
        self._stop_requested = False
        self._push_to_talk_lock = threading.Lock()
        self._push_to_talk_cancel: threading.Event | None = None
        self._push_to_talk_thread: threading.Thread | None = None
        self._backend: _PynputHotkeyBackend | None = None
        self._mouse_backend: _MouseHotkeyBackend | None = None
        self.accessibility_missing = False
        self.input_monitoring_missing = False

    def _start_mouse_backend(self) -> tuple[str, ...]:
        """Start mouse hotkeys. Returns the combos that failed to activate."""
        if not self._mouse_bindings or self._mouse_backend is not None:
            return ()

        if os.name == "nt":
            modifier_state: Callable[[], set[str]] = windows_modifier_state
        else:
            backend = self._backend
            modifier_state = (
                backend.current_modifiers if backend is not None else lambda: set()
            )

        try:
            mouse_backend = _MouseHotkeyBackend(
                self._mouse_bindings,
                self._dispatch,
                self._logger,
                modifier_state,
            )
            mouse_backend.start()
        except Exception:
            # Keyboard hotkeys are unaffected, so this degrades rather than fails.
            self._logger.exception(
                "Mouse hotkeys could not start; keyboard shortcuts are unaffected."
            )
            return tuple(combo for *_binding, combo in self._mouse_bindings)

        self._mouse_backend = mouse_backend
        for *_binding, combo in self._mouse_bindings:
            self._logger.info("Registered mouse hotkey %s.", combo)
        if os.name != "nt":
            self._logger.info(
                "Mouse hotkeys pass the click through on this platform; "
                "only Windows can suppress a single button."
            )
        return ()

    def start(self) -> HotkeyActivationResult:
        if os.name == "nt":
            if self._thread is not None:
                return self._activation_result
            self.accessibility_missing = False
            self.input_monitoring_missing = False
            self._started.clear()
            self._stop_requested = False
            self._thread = threading.Thread(
                target=self._run,
                name="winwhisper-hotkeys",
                daemon=True,
            )
            self._thread.start()
            if not self._started.wait(1.0):
                self._activation_result = HotkeyActivationResult(
                    active=(),
                    failed=self._requested_combos,
                )
                return self._activation_result
            mouse_failed = self._start_mouse_backend()
            if mouse_failed:
                self._activation_result = HotkeyActivationResult(
                    active=self._activation_result.active,
                    failed=self._activation_result.failed + mouse_failed,
                )
            else:
                self._activation_result = HotkeyActivationResult(
                    active=self._activation_result.active
                    + tuple(combo for *_b, combo in self._mouse_bindings),
                    failed=self._activation_result.failed,
                )
            return self._activation_result

        # macOS and Linux: listener-based backend. On macOS this requires the
        # Accessibility permission; on Linux it requires X11 (Wayland needs
        # compositor-specific portals and is not supported yet).
        if self._backend is not None:
            return self._activation_result
        self.accessibility_missing = False
        self.input_monitoring_missing = False
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
        if not _macos_input_monitoring_trusted(prompt=True):
            self.input_monitoring_missing = True
            self._logger.warning(
                "Input Monitoring permission is not granted; global hotkeys "
                "will not work until Speech is enabled under System Settings > "
                "Privacy & Security > Input Monitoring and the app is relaunched."
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
            self._activation_result = HotkeyActivationResult(
                active=(),
                failed=self._requested_combos,
            )
            return self._activation_result
        self._backend = backend
        for _modifiers, _trigger, _action, combo in self._name_bindings:
            self._logger.info("Registered global hotkey %s (listener backend).", combo)
        mouse_failed = self._start_mouse_backend()
        active_mouse = tuple(
            combo
            for *_binding, combo in self._mouse_bindings
            if combo not in mouse_failed
        )
        self._activation_result = HotkeyActivationResult(
            active=tuple(combo for *_binding, combo in self._name_bindings)
            + active_mouse,
            failed=tuple(self._rejected_combos) + mouse_failed,
        )
        return self._activation_result

    def stop(self) -> None:
        self._stop_requested = True
        self._cancel_push_to_talk_poll()

        mouse_backend = self._mouse_backend
        if mouse_backend is not None:
            self._mouse_backend = None
            try:
                mouse_backend.stop()
            except Exception:
                self._logger.warning("Mouse hotkey listener did not stop cleanly.")

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
            registered: list[tuple[int, str, int]] = []
            active_combos: list[str] = []
            failed_combos = list(self._rejected_combos)
            for hotkey_id, fs_modifiers, vk, action, combo in self._bindings:
                if user32.RegisterHotKey(
                    None, hotkey_id, fs_modifiers | _MOD_NOREPEAT, vk
                ):
                    registered.append((hotkey_id, action, vk))
                    active_combos.append(combo)
                    self._logger.info("Registered global hotkey %s.", combo)
                else:
                    failed_combos.append(combo)
                    self._logger.warning(
                        "Could not register hotkey %s; it may already be in use by "
                        "another application. Choose a different combo in settings.",
                        combo,
                    )

            self._activation_result = HotkeyActivationResult(
                active=tuple(active_combos),
                failed=tuple(failed_combos),
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
                        binding = next(
                            ((a, vk) for i, a, vk in registered if i == fired_id),
                            None,
                        )
                        if binding is not None:
                            action, vk = binding
                            self._handle_registered_hotkey(action, vk)
            except Exception:
                self._logger.exception(
                    "Hotkey message loop crashed; re-registering hotkeys."
                )
            finally:
                for hotkey_id, _action, _vk in registered:
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

    def _handle_registered_hotkey(self, action: str, vk: int) -> None:
        self._dispatch(action)
        if action == TOGGLE_ACTION:
            self._start_push_to_talk_poll(vk)

    def _start_push_to_talk_poll(self, vk: int) -> None:
        cancel = threading.Event()
        with self._push_to_talk_lock:
            previous_cancel = self._push_to_talk_cancel
            previous_thread = self._push_to_talk_thread
            self._push_to_talk_cancel = None
            self._push_to_talk_thread = None
        if previous_cancel is not None:
            previous_cancel.set()
        if (
            previous_thread is not None
            and previous_thread is not threading.current_thread()
        ):
            previous_thread.join()

        pressed_at = time.monotonic()
        thread = threading.Thread(
            target=self._poll_push_to_talk,
            args=(vk, cancel, pressed_at),
            name="winwhisper-push-to-talk",
            daemon=True,
        )
        with self._push_to_talk_lock:
            if self._stop_requested:
                cancel.set()
            self._push_to_talk_cancel = cancel
            self._push_to_talk_thread = thread
        thread.start()

    def _cancel_push_to_talk_poll(self) -> None:
        with self._push_to_talk_lock:
            cancel = self._push_to_talk_cancel
            thread = self._push_to_talk_thread
            self._push_to_talk_cancel = None
            self._push_to_talk_thread = None
        if cancel is not None:
            cancel.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join()

    def _poll_push_to_talk(
        self,
        vk: int,
        cancel: threading.Event,
        pressed_at: float,
    ) -> None:
        if os.name != "nt":
            return

        import ctypes

        # Keep this handle private for the same reason as the message loop's
        # user32 handle: shared ctypes function metadata can be clobbered.
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user32.GetAsyncKeyState.restype = ctypes.c_short
        push_to_talk = False
        try:
            while not cancel.is_set():
                if not bool(user32.GetAsyncKeyState(vk) & 0x8000):
                    if push_to_talk and not cancel.is_set():
                        self._dispatch(TOGGLE_RELEASE_ACTION)
                    return
                if time.monotonic() - pressed_at >= PUSH_TO_TALK_HOLD_SECONDS:
                    push_to_talk = True
                cancel.wait(_PUSH_TO_TALK_POLL_SECONDS)
        finally:
            with self._push_to_talk_lock:
                if self._push_to_talk_cancel is cancel:
                    self._push_to_talk_cancel = None
                    self._push_to_talk_thread = None

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


def _macos_input_monitoring_trusted(prompt: bool) -> bool:
    """True unless macOS has denied permission to observe global key events."""
    if sys.platform != "darwin":
        return True
    try:
        from Quartz import (
            CGPreflightListenEventAccess,
            CGRequestListenEventAccess,
        )

        if CGPreflightListenEventAccess():
            return True
        if prompt:
            return bool(CGRequestListenEventAccess())
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


class _MouseHotkeyBackend:
    """Mouse-button hotkeys, on every platform.

    ``RegisterHotKey`` is keyboard-only, so mouse buttons need a listener even
    on Windows where keys deliberately do not use one. The blast radius is much
    smaller than the old keyboard hook: this one only ever swallows a button the
    user explicitly bound, and a failure to install it costs mouse shortcuts
    rather than all dictation.

    Suppression is Windows-only. pynput can suppress a single event there via
    ``win32_event_filter``; on macOS and Linux its only lever is suppressing
    every mouse event, which would be far worse than letting the click through.
    """

    # winuser.h button messages, as (down, up, button-name-or-None-for-x).
    _BUTTON_MESSAGES = {
        0x0201: ("left", True),
        0x0202: ("left", False),
        0x0204: ("right", True),
        0x0205: ("right", False),
        0x0207: ("middle", True),
        0x0208: ("middle", False),
        0x020B: (None, True),  # WM_XBUTTONDOWN, index in mouseData
        0x020C: (None, False),  # WM_XBUTTONUP
    }

    def __init__(
        self,
        bindings: list[tuple[frozenset[str], str, str, str]],
        dispatch: Callable[[str], None],
        logger: Any,
        modifier_state: Callable[[], set[str]],
    ) -> None:
        self._bindings = [(m, b, a) for m, b, a, _combo in bindings]
        self._dispatch = dispatch
        self._logger = logger
        self._modifier_state = modifier_state
        self._listener: Any | None = None
        self._state_lock = threading.Lock()
        self._last_action_at: dict[str, float] = {}
        self._held: set[str] = set()

    def start(self) -> None:
        from pynput import mouse

        kwargs: dict[str, Any] = {}
        if os.name == "nt":
            # Dispatching happens inside the filter, because suppressing an
            # event also stops pynput from delivering it to on_click.
            kwargs["win32_event_filter"] = self._win32_event_filter
        else:
            kwargs["on_click"] = self._on_click
        self._listener = mouse.Listener(**kwargs)
        self._listener.start()

    def stop(self) -> None:
        listener = self._listener
        self._listener = None
        if listener is not None:
            listener.stop()
        self.reset_state()

    def reset_state(self) -> None:
        with self._state_lock:
            self._held.clear()

    def _match(self, button: str) -> str | None:
        """Return the action bound to this button under the current modifiers."""
        try:
            pressed = self._modifier_state()
        except Exception:
            self._logger.exception("Could not read modifier state for a mouse hotkey.")
            return None
        for modifiers, bound_button, action in self._bindings:
            if bound_button == button and modifiers == pressed:
                return action
        return None

    def _fire(self, action: str) -> bool:
        now = time.monotonic()
        with self._state_lock:
            if now - self._last_action_at.get(action, 0.0) < _ACTION_DEBOUNCE_SECONDS:
                return False
            self._last_action_at[action] = now
        self._dispatch(action)
        return True

    def _win32_event_filter(self, msg: int, data: Any) -> None:
        listener = self._listener
        if listener is None:
            return

        suppress = False
        try:
            entry = self._BUTTON_MESSAGES.get(msg)
            if entry is None:
                return
            button, is_press = entry
            if button is None:
                # X buttons pack their index into the high word of mouseData.
                index = (getattr(data, "mouseData", 0) >> 16) & 0xFFFF
                button = {1: "x1", 2: "x2"}.get(index)
                if button is None:
                    return

            if listener_is_suppressed():
                return

            if is_press:
                action = self._match(button)
                if action is None:
                    return
                # Swallow the release too, so the target app never sees a
                # dangling button-up for a click it was never told about.
                with self._state_lock:
                    self._held.add(button)
                # Dispatch before suppressing, never after: suppress_event
                # signals by raising, so anything below it would not run.
                self._fire(action)
                suppress = True
            else:
                with self._state_lock:
                    suppress = button in self._held
                    self._held.discard(button)
        except Exception:
            # pynput tears the hook down if this raises, which would wedge the
            # mouse. Never let that happen; a missed shortcut is recoverable.
            self._logger.exception("Mouse hotkey filter failed; listener kept alive.")
            return

        if suppress:
            # Deliberately outside the try. pynput requests suppression by
            # raising SuppressException, and that exception has to travel up to
            # its own hook handler to take effect. Catching it here would leave
            # the click unsuppressed and log a bogus error for every press.
            listener.suppress_event()

    def _on_click(self, x: int, y: int, button: Any, pressed: bool) -> None:
        try:
            if not pressed or listener_is_suppressed():
                return
            name = getattr(button, "name", None)
            if not name:
                return
            action = self._match(str(name))
            if action is not None:
                self._fire(action)
        except Exception:
            self._logger.exception("Mouse hotkey handler failed; listener kept alive.")


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

    def current_modifiers(self) -> set[str]:
        """Modifiers held right now, so mouse chords can match against them."""
        with self._state_lock:
            return set(self._pressed_modifiers)

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
