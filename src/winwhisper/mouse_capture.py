"""Record the next mouse button press as a hotkey combo.

Backs the "Record" button in hotkey settings: rather than asking people to know
that their thumb button is called ``x1``, let them press it. Whatever the OS
reports is what gets bound, so a mouse with unusual buttons works without this
module knowing anything about that model.
"""
from __future__ import annotations

import os
import threading
from collections.abc import Callable
from typing import Any

from .logger import get_logger
from .mouse_buttons import MODIFIER_REQUIRED_BUTTONS, trigger_for_button_name

CAPTURE_TIMEOUT_SECONDS = 8.0

_MODIFIER_ORDER = ("ctrl", "alt", "shift", "cmd")


class MouseCapture:
    """One-shot listener for the next bindable mouse button."""

    def __init__(
        self,
        on_captured: Callable[[str], None],
        on_cancelled: Callable[[], None] | None = None,
        timeout: float = CAPTURE_TIMEOUT_SECONDS,
    ) -> None:
        self._on_captured = on_captured
        self._on_cancelled = on_cancelled
        self._timeout = timeout
        self._logger = get_logger(__name__)
        self._listener: Any | None = None
        self._keyboard_listener: Any | None = None
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._finished = False
        self._modifiers: set[str] = set()

    def start(self) -> None:
        from pynput import mouse

        if os.name != "nt":
            self._start_modifier_tracking()

        self._listener = mouse.Listener(on_click=self._on_click)
        self._listener.start()
        self._timer = threading.Timer(self._timeout, self._cancel_on_timeout)
        self._timer.daemon = True
        self._timer.start()

    def cancel(self) -> None:
        if self._finish():
            self._notify_cancelled()

    def _start_modifier_tracking(self) -> None:
        """Track modifiers on platforms without a live modifier query."""
        from pynput import keyboard

        from .hotkeys import _MODIFIER_ALIASES

        def on_press(key: Any) -> None:
            alias = _MODIFIER_ALIASES.get(getattr(key, "name", ""))
            if alias:
                self._modifiers.add(alias)

        def on_release(key: Any) -> None:
            alias = _MODIFIER_ALIASES.get(getattr(key, "name", ""))
            if alias:
                self._modifiers.discard(alias)

        self._keyboard_listener = keyboard.Listener(
            on_press=on_press, on_release=on_release
        )
        self._keyboard_listener.start()

    def _current_modifiers(self) -> set[str]:
        if os.name == "nt":
            from .hotkeys import windows_modifier_state

            return windows_modifier_state()
        return set(self._modifiers)

    def _on_click(self, x: int, y: int, button: Any, pressed: bool) -> None:
        try:
            if not pressed:
                return
            name = str(getattr(button, "name", "") or "")
            if not name:
                return

            modifiers = self._current_modifiers()
            # The click that started the capture is a bare left click, so it
            # would otherwise record itself the instant recording begins.
            if name in MODIFIER_REQUIRED_BUTTONS and not modifiers:
                return

            try:
                trigger = trigger_for_button_name(name)
            except ValueError:
                self._logger.warning("Ignoring unsupported mouse button %r.", name)
                return

            if not self._finish():
                return
            self._on_captured(build_combo(modifiers, trigger))
        except Exception:
            self._logger.exception("Mouse capture handler failed.")

    def _cancel_on_timeout(self) -> None:
        if self._finish():
            self._notify_cancelled()

    def _notify_cancelled(self) -> None:
        if self._on_cancelled is None:
            return
        try:
            self._on_cancelled()
        except Exception:
            self._logger.exception("Mouse capture cancel callback failed.")

    def _finish(self) -> bool:
        """Tear down exactly once; returns True for the call that won."""
        with self._lock:
            if self._finished:
                return False
            self._finished = True

        for resource in (self._timer, self._listener, self._keyboard_listener):
            if resource is None:
                continue
            try:
                resource.cancel() if isinstance(resource, threading.Timer) else resource.stop()
            except Exception:
                self._logger.warning("Mouse capture resource did not stop cleanly.")
        self._timer = None
        self._listener = None
        self._keyboard_listener = None
        return True


def build_combo(modifiers: set[str], trigger: str) -> str:
    ordered = [name for name in _MODIFIER_ORDER if name in modifiers]
    return "+".join([*(f"<{name}>" for name in ordered), f"<{trigger}>"])
