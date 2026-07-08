from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from .focus import ScreenPoint
from .logger import get_logger

CommandName = Literal["show", "hide", "stop", "transcribing"]
OverlayState = Literal["hidden", "recording", "transcribing"]

_WIDTH = 152
_HEIGHT = 132
_MARGIN = 24
_CURSOR_OFFSET = 18
_TRANSPARENT_COLOR = "#01030a"
_CENTER = ScreenPoint(76, 66)
_SURFACE_DIAMETER = 72
_BUTTON_DIAMETER = 46
_RING_DIAMETER = 66
_STOP_BUTTON_CENTER = _CENTER
_STOP_BUTTON_RADIUS = _BUTTON_DIAMETER // 2


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


def dragged_overlay_position(
    origin: ScreenPoint,
    press: ScreenPoint,
    pointer: ScreenPoint,
    screen_width: int,
    screen_height: int,
    width: int = _WIDTH,
    height: int = _HEIGHT,
) -> tuple[int, int]:
    x = origin.x + pointer.x - press.x
    y = origin.y + pointer.y - press.y
    x = min(max(_MARGIN, x), max(_MARGIN, screen_width - width - _MARGIN))
    y = min(max(_MARGIN, y), max(_MARGIN, screen_height - height - _MARGIN))
    return x, y


def is_stop_button_point(x: int, y: int) -> bool:
    dx = x - _STOP_BUTTON_CENTER.x
    dy = y - _STOP_BUTTON_CENTER.y
    return dx * dx + dy * dy <= _STOP_BUTTON_RADIUS * _STOP_BUTTON_RADIUS


def sonar_ring_visuals(
    level: float,
    phase: int,
    count: int = 3,
) -> list[tuple[float, float]]:
    clamped_level = min(1.0, max(0.0, level))
    visuals: list[tuple[float, float]] = []
    for index in range(count):
        progress = ((phase / 32.0) + (index / count)) % 1.0
        scale = 1.0 + progress * (1.0 + clamped_level * 0.28)
        opacity = (1.0 - progress) ** 1.8 * (0.24 + clamped_level * 0.22)
        visuals.append((scale, opacity))
    return visuals


def _ring_color(opacity: float) -> str:
    if opacity >= 0.32:
        return "#db4241"
    if opacity >= 0.22:
        return "#a93636"
    if opacity >= 0.12:
        return "#6f2f33"
    return "#3c2024"


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

    def show_transcribing(self) -> None:
        if self._thread is None:
            return
        self._commands.put(OverlayCommand("transcribing"))

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
        state: OverlayState = "hidden"
        phase = 0
        drag_origin: ScreenPoint | None = None
        drag_press: ScreenPoint | None = None
        root.withdraw()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.97)
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
        items = self._draw_overlay(canvas)
        self._set_overlay_state(canvas, items, "hidden")

        def request_stop(event: Any = None) -> str:
            self._set_overlay_state(canvas, items, "transcribing")
            threading.Thread(
                target=self._on_stop,
                name="winwhisper-overlay-stop",
                daemon=True,
            ).start()
            return "break"

        def begin_drag(event: Any) -> str | None:
            nonlocal drag_origin, drag_press
            if is_stop_button_point(int(event.x), int(event.y)):
                return "break"
            drag_origin = ScreenPoint(root.winfo_x(), root.winfo_y())
            drag_press = ScreenPoint(int(event.x_root), int(event.y_root))
            return None

        def drag(event: Any) -> str | None:
            if drag_origin is None or drag_press is None:
                return None
            x, y = dragged_overlay_position(
                drag_origin,
                drag_press,
                ScreenPoint(int(event.x_root), int(event.y_root)),
                root.winfo_screenwidth(),
                root.winfo_screenheight(),
            )
            root.geometry(f"{_WIDTH}x{_HEIGHT}+{x}+{y}")
            return None

        def end_drag(event: Any = None) -> None:
            nonlocal drag_origin, drag_press
            drag_origin = None
            drag_press = None

        canvas.tag_bind("stop_button", "<Button-1>", request_stop)
        canvas.bind("<ButtonPress-1>", begin_drag)
        canvas.bind("<B1-Motion>", drag)
        canvas.bind("<ButtonRelease-1>", end_drag)

        def pump() -> None:
            nonlocal state
            while True:
                try:
                    command = self._commands.get_nowait()
                except queue.Empty:
                    break

                if command.name == "show":
                    self._position(root, command.anchor)
                    state = "recording"
                    self._set_overlay_state(canvas, items, state)
                    root.deiconify()
                    root.lift()
                    root.attributes("-topmost", True)
                elif command.name == "hide":
                    state = "hidden"
                    self._set_overlay_state(canvas, items, state)
                    root.withdraw()
                elif command.name == "transcribing":
                    state = "transcribing"
                    self._set_overlay_state(canvas, items, state)
                    root.deiconify()
                    root.lift()
                    root.attributes("-topmost", True)
                elif command.name == "stop":
                    root.destroy()
                    return

            root.after(50, pump)

        def animate() -> None:
            nonlocal phase
            if state != "hidden":
                phase += 1
                if state == "recording":
                    self._update_rings(canvas, items["rings"], self._current_level(), phase)
                elif state == "transcribing":
                    self._update_spinner(canvas, items["spinner"], phase)
            root.after(75, animate)

        root.after(50, pump)
        root.after(75, animate)
        root.mainloop()

    def _position(self, root: Any, anchor: ScreenPoint | None) -> None:
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        x, y = position_near_anchor(anchor, screen_width, screen_height)
        root.geometry(f"{_WIDTH}x{_HEIGHT}+{x}+{y}")

    def _draw_overlay(self, canvas: Any) -> dict[str, Any]:
        rings = [
            canvas.create_oval(
                *self._circle_bounds(_CENTER, _RING_DIAMETER),
                outline="#6f2528",
                width=2,
                tags=("recording",),
            )
            for _ in range(3)
        ]

        surface_shadow = canvas.create_oval(
            *self._circle_bounds(_CENTER, _SURFACE_DIAMETER + 10),
            fill="#050506",
            outline="#050506",
            tags=("recording", "transcribing"),
        )
        surface = canvas.create_oval(
            *self._circle_bounds(_CENTER, _SURFACE_DIAMETER),
            fill="#1e1e22",
            outline="#3d3d43",
            width=1,
            tags=("recording", "transcribing"),
        )
        highlight = canvas.create_arc(
            *self._circle_bounds(ScreenPoint(_CENTER.x, _CENTER.y - 1), _SURFACE_DIAMETER - 8),
            start=50,
            extent=80,
            style="arc",
            outline="#55555d",
            width=1,
            tags=("recording", "transcribing"),
        )

        button = canvas.create_oval(
            *self._circle_bounds(_CENTER, _BUTTON_DIAMETER),
            fill="#db4241",
            outline="#e24c4a",
            width=1,
            tags=("recording", "stop_button"),
        )
        stop_glyph = self._rounded_rect(
            canvas,
            _CENTER.x - 8,
            _CENTER.y - 8,
            _CENTER.x + 8,
            _CENTER.y + 8,
            4,
            fill="#ffffff",
            outline="#ffffff",
            tags=("recording", "stop_button"),
        )

        spinner_track = canvas.create_oval(
            *self._circle_bounds(_CENTER, 30),
            outline="#4b4b52",
            width=3,
            tags=("transcribing",),
        )
        spinner = canvas.create_arc(
            *self._circle_bounds(_CENTER, 30),
            start=0,
            extent=285,
            style="arc",
            outline="#e24c4a",
            width=3,
            tags=("transcribing",),
        )
        label = canvas.create_text(
            _CENTER.x,
            114,
            text="Transcribing...",
            fill="#ffffff",
            font=("Segoe UI", 11, "normal"),
            tags=("transcribing",),
        )

        return {
            "rings": rings,
            "recording": [*rings, surface_shadow, surface, highlight, button, stop_glyph],
            "transcribing": [surface_shadow, surface, highlight, spinner_track, spinner, label],
            "spinner": spinner,
        }

    def _set_overlay_state(
        self,
        canvas: Any,
        items: dict[str, Any],
        state: OverlayState,
    ) -> None:
        canvas.itemconfigure("recording", state="hidden")
        canvas.itemconfigure("transcribing", state="hidden")
        if state == "recording":
            canvas.itemconfigure("recording", state="normal")
        elif state == "transcribing":
            canvas.itemconfigure("transcribing", state="normal")

    def _update_rings(
        self,
        canvas: Any,
        ring_items: list[int],
        level: float,
        phase: int,
    ) -> None:
        for item, (scale, opacity) in zip(
            ring_items,
            sonar_ring_visuals(level, phase, count=len(ring_items)),
            strict=False,
        ):
            diameter = _RING_DIAMETER * scale
            canvas.coords(item, *self._circle_bounds(_CENTER, diameter))
            canvas.itemconfigure(item, outline=_ring_color(opacity), width=max(1, round(1 + level * 2)))

    def _update_spinner(self, canvas: Any, spinner_item: int, phase: int) -> None:
        canvas.itemconfigure(spinner_item, start=(phase * 32) % 360)

    def _circle_bounds(self, center: ScreenPoint, diameter: float) -> tuple[float, float, float, float]:
        radius = diameter / 2
        return (
            center.x - radius,
            center.y - radius,
            center.x + radius,
            center.y + radius,
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
