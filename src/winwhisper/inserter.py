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

# Linux terminal emulators paste with Ctrl+Shift+V (Ctrl+V does nothing there).
# Matched against the focused window's executable name (see focus.py).
_LINUX_SHIFT_PASTE_PROCESSES = {
    "alacritty",
    "contour",
    "cool-retro-term",
    "deepin-terminal",
    "foot",
    "footclient",
    "ghostty",
    "gnome-terminal-server",
    "kgx",  # GNOME Console
    "kitty",
    "konsole",
    "lxterminal",
    "mate-terminal",
    "ptyxis",
    "qterminal",
    "rxvt",
    "st",
    "terminator",
    "terminology",
    "tilix",
    "urxvt",
    "wezterm-gui",
    "xfce4-terminal",
    "xterm",
}

_MACOS_V_KEYCODE = 0x09


def _send_macos_cmd_v() -> None:
    """Post Cmd+V without asking Text Services for the current key layout.

    pynput resolves character keys through TISCopyCurrentKeyboardInputSource.
    macOS 26 asserts when that API is reached from Speech's transcription
    worker, so use the fixed virtual key code for V instead.
    """
    from Quartz import (
        CGEventCreateKeyboardEvent,
        CGEventPost,
        CGEventSetFlags,
        kCGEventFlagMaskCommand,
        kCGHIDEventTap,
    )

    for pressed in (True, False):
        event = CGEventCreateKeyboardEvent(None, _MACOS_V_KEYCODE, pressed)
        if event is None:
            raise RuntimeError("Could not create macOS paste event")
        CGEventSetFlags(event, kCGEventFlagMaskCommand)
        CGEventPost(kCGHIDEventTap, event)


def resolve_paste_shortcut(paste_mode: str, process_name: str | None) -> PasteShortcut:
    if sys.platform == "darwin":
        # macOS pastes with Cmd+V everywhere, including terminals.
        return "cmd_v"
    if paste_mode == "clipboard_ctrl_shift_v":
        return "ctrl_shift_v"
    if process_name:
        name = process_name.lower()
        if name in _SHIFT_PASTE_PROCESSES:
            return "ctrl_shift_v"
        if sys.platform.startswith("linux") and name in _LINUX_SHIFT_PASTE_PROCESSES:
            return "ctrl_shift_v"
    return "ctrl_v"


def copy_text_to_clipboard(text: str) -> bool:
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

    return True


def insert_text(text: str, shortcut: PasteShortcut = "ctrl_v") -> bool:
    logger = get_logger(__name__)

    if not copy_text_to_clipboard(text):
        return False

    # Synthetic key events from Controller are seen by listener-based hotkey
    # backends and can leave modifier/trigger state poisoned for the next take.
    set_listener_suppressed(True)
    try:
        if sys.platform == "darwin":
            _send_macos_cmd_v()
        else:
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
        # Windows uses RegisterHotKey, which does not observe these synthetic
        # events. Listener-based platforms need a drain window before matching
        # is re-enabled, but the Windows path can return immediately.
        if sys.platform != "win32":
            time.sleep(0.5)
    except Exception as exc:
        logger.warning("Paste failed with %s; leaving text on clipboard.", exc.__class__.__name__)
        copy_text_to_clipboard(text)
        return False
    finally:
        set_listener_suppressed(False)

    return True
