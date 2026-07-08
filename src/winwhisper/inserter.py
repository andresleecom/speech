from __future__ import annotations

import time
from typing import Literal

from .logger import get_logger

PasteShortcut = Literal["ctrl_v", "ctrl_shift_v"]

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

    try:
        from pynput.keyboard import Controller, Key

        keyboard = Controller()
        if shortcut == "ctrl_shift_v":
            with keyboard.pressed(Key.ctrl):
                with keyboard.pressed(Key.shift):
                    keyboard.press("v")
                    keyboard.release("v")
        else:
            with keyboard.pressed(Key.ctrl):
                keyboard.press("v")
                keyboard.release("v")
        time.sleep(0.5)
    except Exception as exc:
        logger.warning("Paste failed with %s; leaving text on clipboard.", exc.__class__.__name__)
        try:
            pyperclip.copy(text)
        except Exception:
            pass
        return False

    return True
