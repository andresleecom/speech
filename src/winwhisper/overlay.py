from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import Any, Literal

from .logger import get_logger

Command = Literal["show", "hide", "stop"]


class RecordingOverlay:
    def __init__(self, on_stop: Callable[[], None]) -> None:
        self._on_stop = on_stop
        self._commands: queue.Queue[Command] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._logger = get_logger(__name__)

    def show(self) -> None:
        self._ensure_thread()
        self._commands.put("show")

    def hide(self) -> None:
        if self._thread is None:
            return
        self._commands.put("hide")

    def stop(self) -> None:
        if self._thread is None:
            return
        self._commands.put("stop")

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
        root.resizable(False, False)
        self._set_toolwindow(root)

        size = 74
        canvas = tk.Canvas(
            root,
            width=size,
            height=size,
            bg="#111827",
            highlightthickness=0,
            bd=0,
        )
        canvas.pack()
        canvas.create_oval(9, 9, 65, 65, fill="#dc2626", outline="#ffffff", width=3)
        canvas.create_rectangle(31, 31, 43, 43, fill="#ffffff", outline="#ffffff")
        canvas.create_text(37, 58, text="REC", fill="#ffffff", font=("Segoe UI", 8, "bold"))

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

                if command == "show":
                    self._position(root, size)
                    root.deiconify()
                    root.lift()
                    root.attributes("-topmost", True)
                elif command == "hide":
                    root.withdraw()
                elif command == "stop":
                    root.destroy()
                    return

            root.after(50, pump)

        root.after(50, pump)
        root.mainloop()

    def _position(self, root: Any, size: int) -> None:
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        x = max(24, screen_width - size - 32)
        y = max(24, screen_height - size - 96)
        root.geometry(f"{size}x{size}+{x}+{y}")

    def _set_toolwindow(self, root: Any) -> None:
        try:
            root.wm_attributes("-toolwindow", True)
        except Exception:
            pass
