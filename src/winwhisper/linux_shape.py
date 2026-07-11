from __future__ import annotations

"""Circular window shape for the Tkinter overlay fallback on Linux/X11.

Tk on X11 has no per-pixel transparency and ignores Windows-only
``-transparentcolor``, so the overlay's key-colour background renders as a
solid box. This clips the toplevel to a circle via the X11 SHAPE extension,
so only the orb is drawn. Best-effort: no-ops on non-Linux, on pure Wayland
without XWayland, or if python-xlib is missing (overlay keeps old behaviour).
"""

import os
import sys
from typing import Any


def _circle_scanlines(cx: int, cy: int, radius: int) -> list[tuple[int, int, int, int]]:
    rects: list[tuple[int, int, int, int]] = []
    for dy in range(-radius, radius + 1):
        half = int((radius * radius - dy * dy) ** 0.5)
        if half <= 0:
            continue
        rects.append((cx - half, cy + dy, 2 * half, 1))
    return rects


def apply_circle_shape(root: Any, center_x: int, center_y: int, radius: int) -> bool:
    if not sys.platform.startswith("linux"):
        return False
    if not os.environ.get("DISPLAY"):
        return False
    try:
        from Xlib import X, display as xdisplay
        from Xlib.ext import shape
    except Exception:
        return False
    try:
        root.update_idletasks()
        xid = root.winfo_id()
        disp = xdisplay.Display()
        if not disp.has_extension("SHAPE"):
            disp.close()
            return False
        win = disp.create_resource_object("window", xid)
        rects = _circle_scanlines(center_x, center_y, radius)
        win.shape_rectangles(shape.SO.Set, shape.SK.Bounding, X.Unsorted, 0, 0, rects)
        disp.flush()
        disp.close()
        return True
    except Exception:
        return False
