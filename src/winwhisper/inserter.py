from __future__ import annotations

import time

from .logger import get_logger


def insert_text(text: str) -> bool:
    logger = get_logger(__name__)

    try:
        import pyperclip
    except ImportError as exc:
        logger.warning("Clipboard dependency is unavailable: %s.", exc.__class__.__name__)
        return False

    saved_text: str | None = None
    try:
        current_clipboard = pyperclip.paste()
        if isinstance(current_clipboard, str):
            saved_text = current_clipboard
    except Exception:
        saved_text = None

    try:
        pyperclip.copy(text)
    except Exception as exc:
        logger.warning("Could not copy text to clipboard: %s.", exc.__class__.__name__)
        return False

    try:
        from pynput.keyboard import Controller, Key

        keyboard = Controller()
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

    if saved_text is not None:
        try:
            pyperclip.copy(saved_text)
        except Exception as exc:
            logger.warning(
                "Could not restore previous clipboard text after paste: %s.",
                exc.__class__.__name__,
            )

    return True
