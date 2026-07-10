from __future__ import annotations

import sys
import time
from typing import Literal

from .hotkeys import set_listener_suppressed
from .logger import get_logger

PasteShortcut = Literal["ctrl_v", "ctrl_shift_v", "cmd_v"]

_SHIFT_PASTE_PROCESSES = {
    "alacritty.exe",
    "conhost.exe",
    "mintty.exe",
    "wezterm-gui.exe",
    "wezterm.exe",
    "windowsterminal.exe",
    "wt.exe",
}


def resolve_paste_shortcut(paste_mode: str, process_name: str | None) -> PasteShortcut:
    if sys.platform == "darwin":
        # macOS pastes with Cmd+V everywhere, including terminals.
        return "cmd_v"
    if paste_mode == "clipboard_ctrl_shift_v":
        return "ctrl_shift_v"
    if process_name and process_name.lower() in _SHIFT_PASTE_PROCESSES:
        return "ctrl_shift_v"
    return "ctrl_v"


def insert_text(text: str, shortcut: PasteShortcut = "ctrl_v") -> bool:
    logger = get_logger(__name__)

    try:
        import pyperclip
    except ImportError as exc:
        logger.warning("Clipboard dependency is unavailable: %s.", exc.__class__.__name__)
        return False

    try:
        pyperclip.copy(text)
    except Exception as exc:
        logger.warning("Could not copy text to clipboard: %s.", exc.__class__.__name__)
        return False

    # Synthetic key events from Controller are seen by listener-based hotkey
    # backends and can leave modifier/trigger state poisoned for the next take.
    set_listener_suppressed(True)
    try:
        from pynput.keyboard import Controller, Key

        keyboard = Controller()
        if shortcut == "cmd_v":
            with keyboard.pressed(Key.cmd):
                keyboard.press("v")
                keyboard.release("v")
        elif shortcut == "ctrl_shift_v":
            with keyboard.pressed(Key.ctrl):
                with keyboard.pressed(Key.shift):
                    keyboard.press("v")
                    keyboard.release("v")
        else:
            with keyboard.pressed(Key.ctrl):
                keyboard.press("v")
                keyboard.release("v")
        # Windows uses RegisterHotKey, which does not observe these synthetic
        # events. Listener-based platforms need a drain window before matching
        # is re-enabled, but the Windows path can return immediately.
        if sys.platform != "win32":
            time.sleep(0.5)
    except Exception as exc:
        logger.warning("Paste failed with %s; leaving text on clipboard.", exc.__class__.__name__)
        try:
            pyperclip.copy(text)
        except Exception:
            pass
        return False
    finally:
        set_listener_suppressed(False)

    return True
