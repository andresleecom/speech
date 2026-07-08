from __future__ import annotations

import math
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from .focus import ScreenPoint
from .logger import get_logger

CommandName = Literal["show", "hide", "stop"]

_WIDTH = 188
_HEIGHT = 54
_MARGIN = 24
_CURSOR_OFFSET = 18
_TRANSPARENT_COLOR = "#01030a"
_WAVEFORM_COUNT = 18


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


def waveform_bar_heights(
    level: float,
    phase: int,
    count: int = _WAVEFORM_COUNT,
    min_height: int = 2,
    max_height: int = 13,
) -> list[int]:
    clamped_level = min(1.0, max(0.0, level))
    activity = 0.16 + clamped_level * 0.84
    heights: list[int] = []
    for index in range(count):
        wave = (math.sin((phase + index) * 0.68) + 1.0) / 2.0
        contour = 0.32 + wave * 0.68
        height = round(min_height + (max_height - min_height) * activity * contour)
        heights.append(max(min_height, min(max_height, height)))
    return heights


class RecordingOverlay:
    def __init__(
        self,
        on_stop: Callable[[], None],
        level_provider: Callable[[], float] | None = None,
    ) -> None:
        self._on_stop = on_stop
        self._level_provider = level_provider or (lambda: 0.0)
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
        is_visible = False
        phase = 0
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
        waveform_items = self._draw_overlay(canvas)

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
            nonlocal is_visible
            while True:
                try:
                    command = self._commands.get_nowait()
                except queue.Empty:
                    break

                if command.name == "show":
                    self._position(root, command.anchor)
                    is_visible = True
                    root.deiconify()
                    root.lift()
                    root.attributes("-topmost", True)
                elif command.name == "hide":
                    is_visible = False
                    root.withdraw()
                elif command.name == "stop":
                    root.destroy()
                    return

            root.after(50, pump)

        def animate() -> None:
            nonlocal phase
            if is_visible:
                phase += 1
                self._update_waveform(
                    canvas,
                    waveform_items,
                    self._current_level(),
                    phase,
                )
            root.after(75, animate)

        root.after(50, pump)
        root.after(75, animate)
        root.mainloop()

    def _position(self, root: Any, anchor: ScreenPoint | None) -> None:
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        x, y = position_near_anchor(anchor, screen_width, screen_height)
        root.geometry(f"{_WIDTH}x{_HEIGHT}+{x}+{y}")

    def _draw_overlay(self, canvas: Any) -> list[int]:
        self._rounded_rect(canvas, 2, 4, 186, 51, 21, fill="#f8fafc", outline="#d6dbe4")
        self._rounded_rect(canvas, 7, 9, 181, 47, 17, fill="#ffffff", outline="#e5e7eb")
        canvas.create_oval(17, 19, 31, 33, fill="#ff375f", outline="#ffb3c1", width=1)
        canvas.create_oval(21, 23, 27, 29, fill="#c9184a", outline="#c9184a")

        waveform_items: list[int] = []
        for index, bar_height in enumerate(waveform_bar_heights(0.0, phase=0)):
            waveform_items.append(
                self._draw_waveform_bar(
                    canvas,
                    index,
                    bar_height,
                    fill="#0a84ff",
                )
            )

        canvas.create_text(
            126,
            18,
            text="Recording",
            fill="#111827",
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        )
        canvas.create_rectangle(172, 29, 180, 37, fill="#111827", outline="#111827")
        canvas.create_text(
            126,
            35,
            text="Stop",
            fill="#6b7280",
            font=("Segoe UI", 8),
            anchor="w",
        )
        return waveform_items

    def _update_waveform(
        self,
        canvas: Any,
        waveform_items: list[int],
        level: float,
        phase: int,
    ) -> None:
        for index, bar_height in enumerate(
            waveform_bar_heights(level, phase, count=len(waveform_items))
        ):
            canvas.coords(
                waveform_items[index],
                *self._waveform_line(index, bar_height),
            )

    def _draw_waveform_bar(self, canvas: Any, index: int, height: int, **kwargs: Any) -> int:
        return canvas.create_line(
            *self._waveform_line(index, height),
            width=2,
            capstyle="round",
            **kwargs,
        )

    def _waveform_line(self, index: int, height: int) -> tuple[int, int, int, int]:
        x = 42 + index * 4
        center_y = 27
        return x, center_y - height // 2, x, center_y + height // 2

    def _rounded_rect(
        self,
        canvas: Any,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        radius: int,
        **kwargs: Any,
    ) -> int:
        return canvas.create_polygon(
            self._rounded_rect_points(x1, y1, x2, y2, radius),
            smooth=True,
            splinesteps=16,
            **kwargs,
        )

    def _rounded_rect_points(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        radius: int,
    ) -> list[int]:
        return [
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

    def _current_level(self) -> float:
        try:
            return min(1.0, max(0.0, float(self._level_provider())))
        except Exception:
            return 0.0

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
