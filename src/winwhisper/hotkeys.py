from __future__ import annotations

import threading
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

# While synthetic paste injects keys, ignore listener events so Controller
# keystrokes cannot poison modifier/trigger tracking.
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


class HotkeyManager:
    """Global hotkey dispatcher built on a raw pynput listener.

    pynput's GlobalHotKeys fails to match combos with named keys such as
    <space> on Windows, so combos are matched here instead: modifier state is
    tracked across press/release events and trigger keys are compared by
    virtual-key code, which also survives the control-character key events
    Windows delivers while Ctrl is held.
    """

    def __init__(
        self,
        hotkey_map: Mapping[str, str],
        on_hotkey: Callable[[str], None],
    ) -> None:
        self._on_hotkey = on_hotkey
        self._listener: Any | None = None
        self._logger = get_logger(__name__)
        self._state_lock = threading.Lock()
        self._pressed_modifiers: set[str] = set()
        self._down_triggers: set[str] = set()
        self._bindings: list[tuple[frozenset[str], str, str]] = []
        for setting_key, action in _ACTIONS.items():
            combo = hotkey_map.get(setting_key)
            if not combo:
                continue
            try:
                modifiers, trigger = parse_combo(combo)
            except ValueError:
                self._logger.warning("Ignoring invalid hotkey combo for %s.", setting_key)
                continue
            self._bindings.append((modifiers, trigger, action))

    def start(self) -> None:
        if self._listener is not None:
            return

        from pynput import keyboard

        self.reset_state()
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.start()

    def stop(self) -> None:
        listener = self._listener
        if listener is None:
            return

        listener.stop()
        self._listener = None
        self.reset_state()

    def reset_state(self) -> None:
        """Clear modifier/trigger tracking after synthetic input or missed releases."""
        with self._state_lock:
            self._pressed_modifiers.clear()
            self._down_triggers.clear()

    def _on_press(self, key: Any) -> None:
        if listener_is_suppressed():
            return

        kind, name = self._describe(key)
        with self._state_lock:
            if kind == "mod":
                self._pressed_modifiers.add(name)
                # A new modifier edge ends the previous chord hold, which
                # recovers when Windows drops a trigger key-up.
                self._down_triggers.clear()
                return
            if name in self._down_triggers:
                return  # key repeat while held
            self._down_triggers.add(name)
            pressed_modifiers = set(self._pressed_modifiers)
            bindings = list(self._bindings)

        for modifiers, trigger, action in bindings:
            if trigger == name and modifiers <= pressed_modifiers:
                self._dispatch(action)
                return

    def _on_release(self, key: Any) -> None:
        if listener_is_suppressed():
            return

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
        vk = getattr(key, "vk", None)
        if vk is not None and (0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A):
            # Letter/digit VKs match ASCII; chars are unreliable under Ctrl.
            return "key", chr(vk).lower()
        char = getattr(key, "char", None)
        if char:
            return "key", char.lower()
        return "key", f"vk{vk}"

    def _dispatch(self, action: str) -> None:
        self._logger.info("Hotkey matched action=%s.", action)
        thread = threading.Thread(
            target=self._run_callback,
            args=(action,),
            name="winwhisper-hotkey-dispatch",
            daemon=True,
        )
        thread.start()

    def _run_callback(self, action: str) -> None:
        try:
            self._on_hotkey(action)
        except Exception:
            self._logger.exception("Hotkey callback failed for action %s.", action)
