from __future__ import annotations

import os
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

# Ignore OS key-repeat / the same physical hold.
_TRIGGER_HOLD_SECONDS = 0.45
# Ignore a second matched action this soon (start+stop double-fire).
_ACTION_DEBOUNCE_SECONDS = 0.35

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
        self._trigger_down_at: dict[str, float] = {}
        self._last_action_at: dict[str, float] = {}
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
        """Clear all modifier/trigger tracking (listener start/stop lifecycle).

        Action debounce timestamps are kept so a still-held chord cannot
        immediately re-fire after reset runs at the end of a callback.
        """
        with self._state_lock:
            self._pressed_modifiers.clear()
            self._down_triggers.clear()
            self._trigger_down_at.clear()

    def reset_trigger_state(self) -> None:
        """Clear only the trigger tracking after an action or synthetic input.

        Unlike :meth:`reset_state`, the pressed-modifier set is preserved. Users
        routinely hold the chord's modifiers (e.g. Ctrl+Alt) across the start and
        stop taps, only lifting the trigger key. Held modifier keys do not re-emit
        key-down events, so wiping ``_pressed_modifiers`` here made every later
        trigger press fail the ``modifiers <= pressed_modifiers`` check, leaving
        the hotkey silently dead until the modifiers were fully released and
        pressed again. Dropping just the trigger tracking still recovers from a
        missed trigger key-up without breaking a held chord.
        """
        with self._state_lock:
            self._down_triggers.clear()
            self._trigger_down_at.clear()

    def _on_press(self, key: Any) -> None:
        if listener_is_suppressed():
            return

        kind, name = self._describe(key)
        now = time.monotonic()
        with self._state_lock:
            if kind == "mod":
                self._pressed_modifiers.add(name)
                # A new modifier edge ends the previous chord hold, which
                # recovers when Windows drops a trigger key-up.
                self._down_triggers.clear()
                self._trigger_down_at.clear()
                return

            if name in self._down_triggers:
                held_for = now - self._trigger_down_at.get(name, now)
                if held_for < _TRIGGER_HOLD_SECONDS:
                    return  # OS key-repeat / same physical hold
                # Missed key-up recovery: treat as a fresh press.
                self._logger.info(
                    "Hotkey trigger %r held without release for %.2fs; re-arming.",
                    name,
                    held_for,
                )

            self._down_triggers.add(name)
            self._trigger_down_at[name] = now
            pressed_modifiers = set(self._pressed_modifiers)
            bindings = list(self._bindings)
            last_action_at = dict(self._last_action_at)

        # On Windows the OS key state is the authoritative, drift-free answer for
        # which modifiers are physically held right now. Prefer it over tracked
        # state, which can drift in either direction: missing a modifier after a
        # reset (dead hotkey) or retaining a stale one after a missed key-up
        # (phantom toggle). Fall back to the tracked snapshot only when the live
        # query is unavailable (non-Windows, or the call failed).
        live_modifiers = self._live_modifiers()
        if live_modifiers is not None:
            pressed_modifiers = live_modifiers

        for modifiers, trigger, action in bindings:
            if trigger != name or not modifiers <= pressed_modifiers:
                continue
            last = last_action_at.get(action, 0.0)
            if now - last < _ACTION_DEBOUNCE_SECONDS:
                self._logger.info(
                    "Hotkey action=%s debounced (%.0fms since last fire).",
                    action,
                    (now - last) * 1000,
                )
                return
            with self._state_lock:
                self._last_action_at[action] = now
            self._dispatch(action)
            return

    def _on_release(self, key: Any) -> None:
        if listener_is_suppressed():
            # Still clear state on releases seen while suppressed so we do not
            # keep phantom "down" keys after paste finishes.
            kind, name = self._describe(key)
            with self._state_lock:
                if kind == "mod":
                    self._pressed_modifiers.discard(name)
                    self._down_triggers.clear()
                    self._trigger_down_at.clear()
                else:
                    self._down_triggers.discard(name)
                    self._trigger_down_at.pop(name, None)
            return

        kind, name = self._describe(key)
        with self._state_lock:
            if kind == "mod":
                self._pressed_modifiers.discard(name)
                self._down_triggers.clear()
                self._trigger_down_at.clear()
                # Chord finished: allow the next take immediately.
                if not self._pressed_modifiers:
                    self._last_action_at.clear()
            else:
                self._down_triggers.discard(name)
                self._trigger_down_at.pop(name, None)

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

    def _live_modifiers(self) -> set[str] | None:
        """Modifiers physically held right now, per the OS key state (Windows).

        Returns ``None`` off Windows or if the query fails, signalling that the
        caller should fall back to tracked state. GetAsyncKeyState covers every
        modifier alias (ctrl/alt/shift/cmd), so a non-None result is a complete,
        authoritative picture of what is physically held.
        """
        if os.name != "nt":
            return None
        try:
            import ctypes

            get_state = ctypes.windll.user32.GetAsyncKeyState
            down = 0x8000
            held: set[str] = set()
            if get_state(0x11) & down:  # VK_CONTROL
                held.add("ctrl")
            if get_state(0x12) & down:  # VK_MENU (Alt / AltGr)
                held.add("alt")
            if get_state(0x10) & down:  # VK_SHIFT
                held.add("shift")
            if (get_state(0x5B) & down) or (get_state(0x5C) & down):  # VK_LWIN/RWIN
                held.add("cmd")
            return held
        except Exception:
            return None

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
        finally:
            # After the action runs, drop only the trigger tracking so a missed
            # Space key-up cannot block the next take. Modifier state is kept so a
            # user still holding Ctrl+Alt across start and stop keeps matching.
            self.reset_trigger_state()
