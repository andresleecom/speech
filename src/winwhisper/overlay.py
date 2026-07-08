from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from .focus import ScreenPoint
from .logger import get_logger

CommandName = Literal["show", "hide", "stop"]

_WIDTH = 168
_HEIGHT = 58
_MARGIN = 24
_CURSOR_OFFSET = 18
_TRANSPARENT_COLOR = "#01030a"


@dataclass(frozen=True)
class OverlayCommand:
    name: CommandName
    anchor: ScreenPoint | None = None


def position_near_anchor(
    anchor: ScreenPoint | None,
    screen_width: int,
    screen_height: int,
    width: int = _WIDTH,
    height: int = _HEIGHT,
) -> tuple[int, int]:
    if anchor is None:
        return (
            max(_MARGIN, screen_width - width - _MARGIN),
            max(_MARGIN, screen_height - height - _MARGIN),
        )

    x = anchor.x + _CURSOR_OFFSET
    y = anchor.y - height // 2
    if x + width > screen_width - _MARGIN:
        x = anchor.x - width - _CURSOR_OFFSET

    x = min(max(_MARGIN, x), max(_MARGIN, screen_width - width - _MARGIN))
    y = min(max(_MARGIN, y), max(_MARGIN, screen_height - height - _MARGIN))
    return x, y


class RecordingOverlay:
    def __init__(self, on_stop: Callable[[], None]) -> None:
        self._on_stop = on_stop
        self._commands: queue.Queue[OverlayCommand] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._logger = get_logger(__name__)

    def show(self, anchor: ScreenPoint | None = None) -> None:
        self._ensure_thread()
        self._commands.put(OverlayCommand("show", anchor))

    def hide(self) -> None:
        if self._thread is None:
            return
        self._commands.put(OverlayCommand("hide"))

    def stop(self) -> None:
        if self._thread is None:
            return
        self._commands.put(OverlayCommand("stop"))

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._run,
                name="winwhisper-recording-overlay",
                daemon=True,
            )
            self._thread.start()

    def _run(self) -> None:
        try:
            import tkinter as tk
        except Exception as exc:
            self._logger.warning(
                "Recording overlay is unavailable: %s.",
                exc.__class__.__name__,
            )
            return

        root = tk.Tk()
        root.withdraw()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.96)
        root.resizable(False, False)
        root.configure(bg=_TRANSPARENT_COLOR)
        self._set_toolwindow(root)
        self._set_transparent_color(root)

        canvas = tk.Canvas(
            root,
            width=_WIDTH,
            height=_HEIGHT,
            bg=_TRANSPARENT_COLOR,
            highlightthickness=0,
            bd=0,
        )
        canvas.pack()
        self._draw_overlay(canvas)

        def request_stop(event: Any = None) -> None:
            root.withdraw()
            threading.Thread(
                target=self._on_stop,
                name="winwhisper-overlay-stop",
                daemon=True,
            ).start()

        root.bind("<Button-1>", request_stop)
        canvas.bind("<Button-1>", request_stop)

        def pump() -> None:
            while True:
                try:
                    command = self._commands.get_nowait()
                except queue.Empty:
                    break

                if command.name == "show":
                    self._position(root, command.anchor)
                    root.deiconify()
                    root.lift()
                    root.attributes("-topmost", True)
                elif command.name == "hide":
                    root.withdraw()
                elif command.name == "stop":
                    root.destroy()
                    return

            root.after(50, pump)

        root.after(50, pump)
        root.mainloop()

    def _position(self, root: Any, anchor: ScreenPoint | None) -> None:
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        x, y = position_near_anchor(anchor, screen_width, screen_height)
        root.geometry(f"{_WIDTH}x{_HEIGHT}+{x}+{y}")

    def _draw_overlay(self, canvas: Any) -> None:
        self._rounded_rect(canvas, 3, 6, 165, 55, 22, fill="#0b1020", outline="#28324a")
        self._rounded_rect(canvas, 7, 10, 161, 51, 18, fill="#111827", outline="#334155")
        canvas.create_oval(17, 18, 39, 40, fill="#ef4444", outline="#fecaca", width=2)
        canvas.create_oval(22, 23, 34, 35, fill="#b91c1c", outline="#b91c1c")

        bar_x = 52
        heights = [10, 18, 13, 22, 15]
        for index, bar_height in enumerate(heights):
            x = bar_x + index * 7
            y1 = 29 - bar_height // 2
            y2 = 29 + bar_height // 2
            self._rounded_rect(canvas, x, y1, x + 4, y2, 2, fill="#38bdf8", outline="#38bdf8")

        canvas.create_text(
            103,
            23,
            text="REC",
            fill="#f8fafc",
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        )
        canvas.create_rectangle(132, 24, 143, 35, fill="#f8fafc", outline="#f8fafc")
        canvas.create_text(
            103,
            38,
            text="Stop",
            fill="#94a3b8",
            font=("Segoe UI", 8),
            anchor="w",
        )

    def _rounded_rect(
        self,
        canvas: Any,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        radius: int,
        **kwargs: Any,
    ) -> None:
        points = [
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]
        canvas.create_polygon(points, smooth=True, splinesteps=16, **kwargs)

    def _set_toolwindow(self, root: Any) -> None:
        try:
            root.wm_attributes("-toolwindow", True)
        except Exception:
            pass

    def _set_transparent_color(self, root: Any) -> None:
        try:
            root.attributes("-transparentcolor", _TRANSPARENT_COLOR)
        except Exception:
            pass
