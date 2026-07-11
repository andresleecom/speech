from __future__ import annotations
import queue
import threading
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from .focus import ScreenPoint
from .logger import get_logger
from .linux_shape import apply_circle_shape
CommandName = Literal["show", "hide", "stop", "transcribing"]
OverlayState = Literal["hidden", "recording", "transcribing"]

_WIDTH = 152
_HEIGHT = 152
_MARGIN = 24
_CURSOR_OFFSET = 18
_TRANSPARENT_COLOR = "#01030a"
_CENTER = ScreenPoint(76, 76)
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
    origin_x: int = 0,
    origin_y: int = 0,
) -> tuple[int, int]:
    """Place the overlay near the anchor, clamped to a screen rectangle.

    ``origin_x`` / ``origin_y`` are the top-left of that rectangle in virtual
    desktop coordinates (primary monitor is usually 0,0; secondary monitors
    may be negative). ``screen_width`` / ``screen_height`` are the rectangle size.
    """
    min_x = origin_x + _MARGIN
    min_y = origin_y + _MARGIN
    max_x = max(min_x, origin_x + screen_width - width - _MARGIN)
    max_y = max(min_y, origin_y + screen_height - height - _MARGIN)

    if anchor is None:
        # Lower-right of the work area, but not glued to a corner that can
        # sit under the taskbar on tall portrait displays.
        return (
            max(min_x, max_x - _MARGIN),
            max(min_y, origin_y + int(screen_height * 0.62) - height // 2),
        )

    x = anchor.x + _CURSOR_OFFSET
    y = anchor.y - height // 2
    if x + width > origin_x + screen_width - _MARGIN:
        x = anchor.x - width - _CURSOR_OFFSET

    x = min(max(min_x, x), max_x)
    y = min(max(min_y, y), max_y)
    return x, y


def dragged_overlay_position(
    origin: ScreenPoint,
    press: ScreenPoint,
    pointer: ScreenPoint,
    screen_width: int,
    screen_height: int,
    width: int = _WIDTH,
    height: int = _HEIGHT,
    origin_x: int = 0,
    origin_y: int = 0,
) -> tuple[int, int]:
    min_x = origin_x + _MARGIN
    min_y = origin_y + _MARGIN
    max_x = max(min_x, origin_x + screen_width - width - _MARGIN)
    max_y = max(min_y, origin_y + screen_height - height - _MARGIN)

    x = origin.x + pointer.x - press.x
    y = origin.y + pointer.y - press.y
    x = min(max(min_x, x), max_x)
    y = min(max(min_y, y), max_y)
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
        max_scale = 1.9 + clamped_level * 0.1
        scale = 1.0 + progress * (max_scale - 1.0)
        opacity = (1.0 - progress) ** 2.2 * (0.13 + clamped_level * 0.06)
        visuals.append((scale, opacity))
    return visuals


def render_orb_frame(
    state: OverlayState,
    level: float = 0.0,
    phase: int = 0,
) -> Any:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    scale = 4
    image = Image.new("RGBA", (_WIDTH * scale, _HEIGHT * scale), (0, 0, 0, 0))

    def s(value: float) -> int:
        return round(value * scale)

    def bounds(center: ScreenPoint, diameter: float) -> tuple[int, int, int, int]:
        radius = diameter / 2
        return (
            s(center.x - radius),
            s(center.y - radius),
            s(center.x + radius),
            s(center.y + radius),
        )

    def composite_blur(
        ellipse_bounds: tuple[int, int, int, int],
        fill: tuple[int, int, int, int],
        blur_radius: float,
    ) -> None:
        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        layer_draw = ImageDraw.Draw(layer)
        layer_draw.ellipse(ellipse_bounds, fill=fill)
        image.alpha_composite(layer.filter(ImageFilter.GaussianBlur(s(blur_radius))))

    draw = ImageDraw.Draw(image)

    if state == "recording":
        for ring_scale, opacity in sonar_ring_visuals(level, phase):
            alpha = round(opacity * 255)
            draw.ellipse(
                bounds(_CENTER, _RING_DIAMETER * ring_scale),
                fill=(219, 66, 65, alpha),
            )

    composite_blur(bounds(_CENTER, _SURFACE_DIAMETER + 13), (0, 0, 0, 120), 5)
    draw.ellipse(
        bounds(_CENTER, _SURFACE_DIAMETER),
        fill=(30, 30, 34, 184),
        outline=(255, 255, 255, 31),
        width=s(1),
    )
    draw.arc(
        bounds(ScreenPoint(_CENTER.x, _CENTER.y - 1), _SURFACE_DIAMETER - 8),
        start=50,
        end=130,
        fill=(255, 255, 255, 30),
        width=s(1),
    )

    if state == "transcribing":
        spinner_bounds = bounds(_CENTER, 30)
        draw.ellipse(spinner_bounds, outline=(255, 255, 255, 42), width=s(3))
        draw.arc(
            spinner_bounds,
            start=(phase * 32) % 360,
            end=((phase * 32) % 360) + 285,
            fill=(226, 76, 74, 255),
            width=s(3),
        )
        label_y = s(_CENTER.y + 44)
        try:
            font = ImageFont.truetype("segoeui.ttf", s(11))
        except Exception:
            font = None
        text = "Transcribing..."
        text_bbox = draw.textbbox((0, 0), text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        draw.text(
            (s(_CENTER.x) - text_width // 2, label_y),
            text,
            fill=(255, 255, 255, 178),
            font=font,
        )
    else:
        composite_blur(bounds(_CENTER, _BUTTON_DIAMETER + 6), (126, 29, 31, 120), 3)
        draw.ellipse(
            bounds(_CENTER, _BUTTON_DIAMETER),
            fill=(219, 66, 65, 255),
            outline=(226, 76, 74, 255),
            width=s(1),
        )
        glyph_radius = s(4)
        glyph_bounds = (
            s(_CENTER.x - 7.5),
            s(_CENTER.y - 7.5),
            s(_CENTER.x + 7.5),
            s(_CENTER.y + 7.5),
        )
        draw.rounded_rectangle(
            glyph_bounds,
            radius=glyph_radius,
            fill=(255, 255, 255, 255),
        )

    return image.resize((_WIDTH, _HEIGHT), Image.Resampling.LANCZOS)


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
        self._logger.info("Overlay show queued (anchor=%s).", anchor)

    def hide(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            return
        self._commands.put(OverlayCommand("hide"))
        self._logger.info("Overlay hide queued.")

    def show_transcribing(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            # Ensure the overlay thread exists so "Transcribing..." can appear
            # even if show() never started a window yet.
            self._ensure_thread()
        self._commands.put(OverlayCommand("transcribing"))
        self._logger.info("Overlay transcribing queued.")

    def stop(self) -> None:
        if self._thread is None:
            return
        if self._thread.is_alive():
            self._commands.put(OverlayCommand("stop"))
        self._thread = None

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            # Drop stale commands from a previous dead overlay loop so a
            # leftover "stop" cannot kill the replacement window immediately.
            self._drain_commands_unlocked()
            self._thread = threading.Thread(
                target=self._run,
                name="winwhisper-recording-overlay",
                daemon=True,
            )
            self._thread.start()
            self._logger.info("Overlay worker thread started.")

    def _drain_commands_unlocked(self) -> None:
        while True:
            try:
                self._commands.get_nowait()
            except queue.Empty:
                break

    def _run(self) -> None:
        if os.name == "nt":
            try:
                from .native_overlay import run_native_overlay

                run_native_overlay(
                    self._commands,
                    self._on_stop,
                    self._current_level,
                    self._logger,
                )
                return
            except Exception as exc:
                self._logger.warning(
                    "Native recording overlay is unavailable; falling back to Tkinter (%s).",
                    exc.__class__.__name__,
                )

        if sys.platform == "darwin":
            # AppKit (and therefore Tk) must run on the main thread on macOS,
            # so the Tk fallback would abort the process. The native macOS orb
            # schedules its AppKit work onto the main queue instead.
            try:
                from .native_overlay_mac import run_native_overlay_mac

                run_native_overlay_mac(
                    self._commands,
                    self._on_stop,
                    self._current_level,
                    self._logger,
                )
                return
            except Exception as exc:
                self._logger.warning(
                    "macOS recording orb is unavailable (%s); running without "
                    "a visual orb - watch the tray icon for recording status.",
                    exc.__class__.__name__,
                )
            while True:
                command = self._commands.get()
                if command.name == "stop":
                    return

        try:
            import tkinter as tk
            from PIL import ImageTk
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
        apply_circle_shape(root, _CENTER.x, _CENTER.y, _SURFACE_DIAMETER // 2 + 2)
        photo = ImageTk.PhotoImage(
            render_orb_frame("recording", self._current_level(), phase)
        )
        image_item = canvas.create_image(0, 0, anchor="nw", image=photo)
        canvas.image = photo

        def update_frame(next_state: OverlayState) -> None:
            next_photo = ImageTk.PhotoImage(
                render_orb_frame(next_state, self._current_level(), phase)
            )
            canvas.itemconfigure(image_item, image=next_photo)
            canvas.image = next_photo

        def request_stop(event: Any = None) -> str:
            nonlocal state
            state = "transcribing"
            update_frame(state)
            threading.Thread(
                target=self._on_stop,
                name="winwhisper-overlay-stop",
                daemon=True,
            ).start()
            return "break"

        def begin_drag(event: Any) -> str | None:
            nonlocal drag_origin, drag_press
            if is_stop_button_point(int(event.x), int(event.y)):
                return request_stop(event)
            drag_origin = ScreenPoint(root.winfo_x(), root.winfo_y())
            drag_press = ScreenPoint(int(event.x_root), int(event.y_root))
            return None

        def drag(event: Any) -> str | None:
            if drag_origin is None or drag_press is None:
                return None
            origin_x, origin_y, screen_width, screen_height = _tk_virtual_screen_bounds(root)
            x, y = dragged_overlay_position(
                drag_origin,
                drag_press,
                ScreenPoint(int(event.x_root), int(event.y_root)),
                screen_width,
                screen_height,
                origin_x=origin_x,
                origin_y=origin_y,
            )
            root.geometry(f"{_WIDTH}x{_HEIGHT}+{x}+{y}")
            return None

        def end_drag(event: Any = None) -> None:
            nonlocal drag_origin, drag_press
            drag_origin = None
            drag_press = None

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
                    update_frame(state)
                    root.deiconify()
                    root.lift()
                    root.attributes("-topmost", True)
                    self._reassert_circle_shape(root)
                elif command.name == "hide":
                    state = "hidden"
                    root.withdraw()
                elif command.name == "transcribing":
                    state = "transcribing"
                    update_frame(state)
                    root.deiconify()
                    root.lift()
                    root.attributes("-topmost", True)
                    self._reassert_circle_shape(root)
                elif command.name == "stop":
                    root.destroy()
                    return

            root.after(50, pump)

        def animate() -> None:
            nonlocal phase
            if state != "hidden":
                phase += 1
                update_frame(state)
            root.after(75, animate)

        root.after(50, pump)
        root.after(75, animate)
        root.mainloop()

    def _position(self, root: Any, anchor: ScreenPoint | None) -> None:
        origin_x, origin_y, screen_width, screen_height = _tk_monitor_work_area(root, anchor)
        x, y = position_near_anchor(
            anchor,
            screen_width,
            screen_height,
            origin_x=origin_x,
            origin_y=origin_y,
        )
        root.geometry(f"{_WIDTH}x{_HEIGHT}+{x}+{y}")

    def _reassert_circle_shape(self, root: Any, attempts: int = 6) -> None:
        """Clip the Tk overlay to a circle on X11, re-asserting a few times.

        The window background is an opaque key colour that Windows hides via
        ``-transparentcolor``. X11 ignores that attribute, so the X11 SHAPE
        circle is the only thing keeping the dark 152x152 box from showing.
        A shape set before an override-redirect window is fully mapped by the
        compositor can be dropped, which leaves the box visible on some shows;
        re-asserting over the first few frames makes the clip reliable.
        """
        try:
            root.update_idletasks()
        except Exception:
            pass
        shaped = apply_circle_shape(
            root, _CENTER.x, _CENTER.y, _SURFACE_DIAMETER // 2 + 2
        )
        if attempts <= 1:
            self._logger.info("Overlay circle shape applied=%s", shaped)
            return
        try:
            root.after(80, lambda: self._reassert_circle_shape(root, attempts - 1))
        except Exception:
            pass

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


def _tk_monitor_work_area(root: Any, anchor: ScreenPoint | None) -> tuple[int, int, int, int]:
    if os.name == "nt":
        try:
            from .native_overlay import _monitor_work_area

            return _monitor_work_area(anchor)
        except Exception:
            pass
    return 0, 0, int(root.winfo_screenwidth()), int(root.winfo_screenheight())


def _tk_virtual_screen_bounds(root: Any) -> tuple[int, int, int, int]:
    if os.name == "nt":
        try:
            from .native_overlay import _virtual_screen_bounds

            return _virtual_screen_bounds()
        except Exception:
            pass
    return 0, 0, int(root.winfo_screenwidth()), int(root.winfo_screenheight())
