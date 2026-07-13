"""Window shape for the Tkinter overlay fallback on Linux/X11.

Tk on X11 has no per-pixel window transparency. Mirror the rendered frame's
alpha channel into the X11 SHAPE extension so the existing orb, rings, spinner,
and label stay visible without an opaque rectangular background.
"""

from __future__ import annotations

import os
import sys
from typing import Any

_SESSION_ATTRIBUTE = "_winwhisper_x11_shape_session"


def _alpha_rectangles(image: Any) -> list[tuple[int, int, int, int]]:
    alpha = image.getchannel("A")
    pixels = alpha.load()
    width, height = image.size
    rectangles: list[tuple[int, int, int, int]] = []

    for y in range(height):
        start: int | None = None
        for x in range(width + 1):
            visible = x < width and int(pixels[x, y]) > 0
            if visible and start is None:
                start = x
            elif not visible and start is not None:
                rectangles.append((start, y, x - start, 1))
                start = None

    return rectangles


def _shape_session(root: Any) -> tuple[Any, Any, Any, Any, Any] | None:
    session = getattr(root, _SESSION_ATTRIBUTE, None)
    if session is not None:
        return session

    if not sys.platform.startswith("linux"):
        return None
    if not os.environ.get("DISPLAY"):
        return None

    try:
        from Xlib import X, display as xdisplay
        from Xlib.ext import shape
    except Exception:
        return None

    disp = None
    try:
        root.update_idletasks()
        xid = root.winfo_id()
        disp = xdisplay.Display()
        if not disp.has_extension("SHAPE"):
            disp.close()
            return None
        win = disp.create_resource_object("window", xid)
        session = (
            disp,
            win,
            shape.SO.Set,
            shape.SK.Bounding,
            X.Unsorted,
        )
        setattr(root, _SESSION_ATTRIBUTE, session)
        return session
    except Exception:
        if disp is not None:
            try:
                disp.close()
            except Exception:
                pass
        return None


def apply_image_shape(root: Any, image: Any) -> bool:
    session = _shape_session(root)
    if session is None:
        return False

    disp, win, operation, destination_kind, ordering = session
    try:
        win.shape_rectangles(
            operation,
            destination_kind,
            ordering,
            0,
            0,
            _alpha_rectangles(image),
        )
        disp.sync()
        return True
    except Exception:
        close_image_shape(root)
        return False


def close_image_shape(root: Any) -> None:
    session = getattr(root, _SESSION_ATTRIBUTE, None)
    if session is None:
        return
    try:
        delattr(root, _SESSION_ATTRIBUTE)
    except Exception:
        pass
    try:
        session[0].close()
    except Exception:
        pass
