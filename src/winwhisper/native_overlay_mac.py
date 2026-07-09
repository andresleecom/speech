from __future__ import annotations

import io
import queue
import threading
from typing import Any, Callable

from .overlay import (
    OverlayCommand,
    OverlayState,
    _HEIGHT,
    _MARGIN,
    _WIDTH,
    is_stop_button_point,
    render_orb_frame,
)

_TICK_SECONDS = 0.075
_MOUSE_OFFSET = 18


def run_native_overlay_mac(
    commands: "queue.Queue[OverlayCommand]",
    on_stop: Callable[[], None],
    level_provider: Callable[[], float],
    logger: Any,
) -> None:
    """Drive the AppKit recording orb from the overlay worker thread.

    AppKit objects may only be touched on the main thread, which is running
    pystray's NSApplication loop. This function stays on the worker thread:
    it renders orb frames with PIL and schedules every AppKit mutation onto
    the main queue via NSOperationQueue. If the run loop is not spinning yet,
    blocks simply wait in the queue.
    """
    _MacOrb(commands, on_stop, level_provider, logger).run()


class _MacOrb:
    def __init__(
        self,
        commands: "queue.Queue[OverlayCommand]",
        on_stop: Callable[[], None],
        level_provider: Callable[[], float],
        logger: Any,
    ) -> None:
        self._commands = commands
        self._on_stop = on_stop
        self._level_provider = level_provider
        self._logger = logger
        self._state: OverlayState = "hidden"
        self._phase = 0
        self._window: Any | None = None
        self._view: Any | None = None
        self._window_ready = threading.Event()

    # ---- worker-thread loop -------------------------------------------------

    def run(self) -> None:
        self._on_main(self._create_window)
        while True:
            try:
                command = self._commands.get(timeout=_TICK_SECONDS)
            except queue.Empty:
                command = None

            if command is not None:
                if command.name == "show":
                    self._state = "recording"
                    self._present(reposition=True)
                    self._logger.info("macOS orb shown (recording).")
                elif command.name == "transcribing":
                    self._state = "transcribing"
                    self._present(reposition=self._window_hidden())
                    self._logger.info("macOS orb shown (transcribing).")
                elif command.name == "hide":
                    self._state = "hidden"
                    self._on_main(self._order_out)
                elif command.name == "stop":
                    self._state = "hidden"
                    self._on_main(self._close_window)
                    return

            if self._state != "hidden":
                self._phase += 1
                self._push_frame()

    def _current_level(self) -> float:
        try:
            return min(1.0, max(0.0, float(self._level_provider())))
        except Exception:
            return 0.0

    def _render_png(self) -> bytes:
        image = render_orb_frame(self._state, self._current_level(), self._phase)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def _present(self, reposition: bool) -> None:
        png = self._render_png()
        self._on_main(lambda: self._show_on_main(png, reposition))

    def _push_frame(self) -> None:
        png = self._render_png()
        self._on_main(lambda: self._set_image_on_main(png))

    def _window_hidden(self) -> bool:
        window = self._window
        try:
            return window is None or not bool(window.isVisible())
        except Exception:
            return True

    # ---- main-thread blocks -------------------------------------------------

    def _on_main(self, block: Callable[[], None]) -> None:
        from Foundation import NSOperationQueue

        def safe_block() -> None:
            try:
                block()
            except Exception:
                self._logger.exception("macOS orb main-thread block failed.")

        NSOperationQueue.mainQueue().addOperationWithBlock_(safe_block)

    def _create_window(self) -> None:
        import AppKit

        mask = (
            AppKit.NSWindowStyleMaskBorderless
            | AppKit.NSWindowStyleMaskNonactivatingPanel
        )
        window = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            AppKit.NSMakeRect(0, 0, _WIDTH, _HEIGHT),
            mask,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        window.setLevel_(AppKit.NSStatusWindowLevel)
        window.setOpaque_(False)
        window.setBackgroundColor_(AppKit.NSColor.clearColor())
        window.setHasShadow_(False)  # the orb image carries its own shadow
        window.setHidesOnDeactivate_(False)
        window.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        view = _orb_view_class().alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, _WIDTH, _HEIGHT)
        )
        view.owner = self
        window.setContentView_(view)
        self._window = window
        self._view = view
        self._window_ready.set()

    def _show_on_main(self, png: bytes, reposition: bool) -> None:
        window = self._window
        view = self._view
        if window is None or view is None:
            return
        self._set_image_on_main(png)
        if reposition:
            self._position_near_mouse(window)
        window.orderFrontRegardless()

    def _set_image_on_main(self, png: bytes) -> None:
        import AppKit
        from Foundation import NSData

        view = self._view
        if view is None:
            return
        data = NSData.dataWithBytes_length_(png, len(png))
        view.image = AppKit.NSImage.alloc().initWithData_(data)
        view.setNeedsDisplay_(True)

    def _position_near_mouse(self, window: Any) -> None:
        import AppKit

        mouse = AppKit.NSEvent.mouseLocation()  # bottom-left screen coords
        screen = None
        for candidate in AppKit.NSScreen.screens():
            if AppKit.NSPointInRect(mouse, candidate.frame()):
                screen = candidate
                break
        if screen is None:
            screen = AppKit.NSScreen.mainScreen()
        work = screen.visibleFrame()

        x = mouse.x + _MOUSE_OFFSET
        y = mouse.y - _HEIGHT / 2
        x = max(work.origin.x + _MARGIN, min(x, work.origin.x + work.size.width - _WIDTH - _MARGIN))
        y = max(work.origin.y + _MARGIN, min(y, work.origin.y + work.size.height - _HEIGHT - _MARGIN))
        window.setFrameOrigin_(AppKit.NSMakePoint(x, y))

    def _order_out(self) -> None:
        window = self._window
        if window is not None:
            window.orderOut_(None)

    def _close_window(self) -> None:
        window = self._window
        self._window = None
        self._view = None
        if window is not None:
            window.orderOut_(None)
            window.close()

    # ---- called from the view (main thread) ---------------------------------

    def request_stop(self) -> None:
        self._state = "transcribing"
        threading.Thread(
            target=self._on_stop,
            name="winwhisper-overlay-stop",
            daemon=True,
        ).start()


_ORB_VIEW_CLASS: Any | None = None


def _orb_view_class() -> Any:
    """Create the NSView subclass lazily (AppKit must not load at import time)."""
    global _ORB_VIEW_CLASS
    if _ORB_VIEW_CLASS is not None:
        return _ORB_VIEW_CLASS

    import AppKit

    class _SpeechOrbView(AppKit.NSView):
        image = None
        owner = None
        _drag_window_origin = None
        _drag_mouse_start = None

        def isFlipped(self) -> bool:
            # Top-left origin so hit testing matches the shared orb geometry.
            return True

        def drawRect_(self, rect) -> None:
            image = self.image
            if image is None:
                return
            image.drawInRect_fromRect_operation_fraction_respectFlipped_hints_(
                self.bounds(),
                AppKit.NSZeroRect,
                AppKit.NSCompositingOperationSourceOver,
                1.0,
                True,
                None,
            )

        def mouseDown_(self, event) -> None:
            point = self.convertPoint_fromView_(event.locationInWindow(), None)
            owner = self.owner
            if owner is not None and is_stop_button_point(int(point.x), int(point.y)):
                owner.request_stop()
                return
            self._drag_window_origin = self.window().frame().origin
            self._drag_mouse_start = AppKit.NSEvent.mouseLocation()

        def mouseDragged_(self, event) -> None:
            origin = self._drag_window_origin
            start = self._drag_mouse_start
            if origin is None or start is None:
                return
            mouse = AppKit.NSEvent.mouseLocation()
            self.window().setFrameOrigin_(
                AppKit.NSMakePoint(
                    origin.x + (mouse.x - start.x),
                    origin.y + (mouse.y - start.y),
                )
            )

        def mouseUp_(self, event) -> None:
            self._drag_window_origin = None
            self._drag_mouse_start = None

    _ORB_VIEW_CLASS = _SpeechOrbView
    return _ORB_VIEW_CLASS
