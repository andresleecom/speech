from __future__ import annotations

import sys
import threading
from collections.abc import Callable, Mapping
from typing import Any

from .branding import APP_NAME
from .hotkey_actions import HOTKEY_ACTIONS, HotkeyAction
from .hotkey_settings import display_hotkey
from .logger import get_logger

SaveHotkeys = Callable[[dict[str, str]], None]

_ACCENT = "#DB4241"


class HotkeySettingsWindow:
    """Open one non-blocking hotkey editor using the platform's GUI loop."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._is_open = False
        self._logger = get_logger(__name__)

    def show(
        self,
        hotkeys: Mapping[str, str],
        on_save: SaveHotkeys,
        language_favorites: object = None,
    ) -> None:
        with self._lock:
            if self._is_open:
                return
            self._is_open = True

        snapshot = dict(hotkeys)
        favorites_snapshot = language_favorites
        if sys.platform == "darwin":
            self._show_macos(snapshot, on_save, favorites_snapshot)
            return

        threading.Thread(
            target=self._run_tk,
            args=(snapshot, on_save, favorites_snapshot),
            name="winwhisper-hotkey-settings",
            daemon=True,
        ).start()

    def _mark_closed(self) -> None:
        with self._lock:
            self._is_open = False

    def _run_tk(
        self,
        hotkeys: dict[str, str],
        on_save: SaveHotkeys,
        language_favorites: object,
    ) -> None:
        try:
            _run_tk_dialog(
                hotkeys,
                on_save,
                platform=sys.platform,
                language_favorites=language_favorites,
            )
        except Exception:
            self._logger.exception("Hotkey settings window failed.")
        finally:
            self._mark_closed()

    def _show_macos(
        self,
        hotkeys: dict[str, str],
        on_save: SaveHotkeys,
        language_favorites: object,
    ) -> None:
        try:
            from Foundation import NSOperationQueue

            def present() -> None:
                try:
                    _run_macos_dialog(hotkeys, on_save, language_favorites)
                except Exception:
                    self._logger.exception("macOS hotkey settings window failed.")
                finally:
                    self._mark_closed()

            NSOperationQueue.mainQueue().addOperationWithBlock_(present)
        except Exception:
            self._logger.exception("Could not schedule the macOS settings window.")
            self._mark_closed()


def _choice_labels(
    platform: str,
    hotkeys: Mapping[str, str],
    action: HotkeyAction,
) -> tuple[str, ...]:
    values = ["Disabled"]
    values.extend(
        display_hotkey(combo, platform=platform)
        for combo in action.suggestions(platform)
    )
    current = hotkeys.get(action.setting_key)
    if current:
        values.append(display_hotkey(current, platform=platform))
    return tuple(dict.fromkeys(values))


def _make_record_command(
    root: Any,
    button: Any,
    value: Any,
    setting_key: str,
    captures: dict[str, Any],
    platform: str,
    error_setter: Callable[[str], None],
) -> Callable[[], None]:
    """Build the per-row Record handler.

    Capture callbacks arrive on a listener thread, so every UI touch is bounced
    back through ``root.after``. Tk is not thread-safe and will crash or hang if
    widgets are poked from anywhere but its own loop.
    """
    from .mouse_capture import MouseCapture

    def restore() -> None:
        button.configure(text="Record")
        captures.pop(setting_key, None)

    def on_captured(combo: str) -> None:
        def apply() -> None:
            value.set(display_hotkey(combo, platform=platform))
            error_setter("")
            restore()

        root.after(0, apply)

    def on_cancelled() -> None:
        def apply() -> None:
            error_setter("No mouse button detected. Try again, or type a shortcut.")
            restore()

        root.after(0, apply)

    def start() -> None:
        existing = captures.get(setting_key)
        if existing is not None:
            existing.cancel()
            restore()
            return

        capture = MouseCapture(on_captured, on_cancelled)
        try:
            capture.start()
        except Exception:
            get_logger(__name__).exception("Mouse capture could not start.")
            error_setter("Mouse capture is unavailable on this system.")
            return
        captures[setting_key] = capture
        button.configure(text="Press a button...")
        error_setter("Press a mouse button now. Left click needs a modifier.")

    return start


def _run_tk_dialog(
    hotkeys: dict[str, str],
    on_save: SaveHotkeys,
    *,
    platform: str,
    language_favorites: object = None,
) -> None:
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title(f"{APP_NAME} Settings — Hotkeys")
    root.resizable(False, False)
    root.configure(bg="#F7F7F8")

    frame = tk.Frame(root, bg="#F7F7F8", padx=24, pady=22)
    frame.grid(row=0, column=0, sticky="nsew")

    tk.Label(
        frame,
        text="Hotkey settings",
        bg="#F7F7F8",
        fg="#1E1E22",
        font=("Segoe UI", 16, "bold"),
        anchor="w",
    ).grid(row=0, column=0, columnspan=2, sticky="w")
    tk.Label(
        frame,
        text=(
            "Choose a shortcut, type one such as Ctrl + Alt + Space, or press "
            "Record and click a mouse button."
        ),
        bg="#F7F7F8",
        fg="#62626A",
        font=("Segoe UI", 9),
        anchor="w",
    ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 18))

    values: dict[str, tk.StringVar] = {}
    captures: dict[str, Any] = {}
    for row, action in enumerate(HOTKEY_ACTIONS, start=2):
        tk.Label(
            frame,
            text=action.label_for_favorites(language_favorites),
            bg="#F7F7F8",
            fg="#2B2B30",
            font=("Segoe UI", 9),
            anchor="w",
        ).grid(row=row, column=0, sticky="w", padx=(0, 18), pady=6)
        value = tk.StringVar(
            value=display_hotkey(
                hotkeys.get(action.setting_key),
                platform=platform,
            )
        )
        values[action.setting_key] = value
        ttk.Combobox(
            frame,
            textvariable=value,
            values=_choice_labels(platform, hotkeys, action),
            width=30,
        ).grid(row=row, column=1, sticky="ew", pady=6)

        record_button = tk.Button(
            frame,
            text="Record",
            padx=10,
            pady=4,
            relief="flat",
            bg="#E7E7EA",
            activebackground="#DCDCE0",
            fg="#303036",
        )
        record_button.grid(row=row, column=2, sticky="w", padx=(8, 0), pady=6)
        record_button.configure(
            command=_make_record_command(
                root,
                record_button,
                value,
                action.setting_key,
                captures,
                platform,
                error_setter=lambda message: error.set(message),
            )
        )

    error = tk.StringVar(value="")
    tk.Label(
        frame,
        textvariable=error,
        bg="#F7F7F8",
        fg=_ACCENT,
        font=("Segoe UI", 9),
        justify="left",
        wraplength=450,
        anchor="w",
    ).grid(
        row=len(HOTKEY_ACTIONS) + 2,
        column=0,
        columnspan=2,
        sticky="ew",
        pady=(12, 4),
    )

    actions = tk.Frame(frame, bg="#F7F7F8")
    actions.grid(
        row=len(HOTKEY_ACTIONS) + 3,
        column=0,
        columnspan=2,
        sticky="e",
        pady=(12, 0),
    )

    def close() -> None:
        # Leaving a capture running would keep a mouse listener alive with no
        # window to report into.
        for capture in list(captures.values()):
            capture.cancel()
        captures.clear()
        root.destroy()

    def save() -> None:
        try:
            on_save({key: value.get() for key, value in values.items()})
        except Exception as exc:
            error.set(str(exc) or "The hotkey settings could not be saved.")
            return
        close()

    tk.Button(
        actions,
        text="Cancel",
        command=close,
        padx=14,
        pady=7,
        relief="flat",
        bg="#E7E7EA",
        activebackground="#DCDCE0",
        fg="#303036",
    ).pack(side="left", padx=(0, 8))
    tk.Button(
        actions,
        text="Save hotkeys",
        command=save,
        padx=14,
        pady=7,
        relief="flat",
        bg=_ACCENT,
        activebackground="#C93635",
        fg="white",
        activeforeground="white",
    ).pack(side="left")

    root.bind("<Return>", lambda event: save())
    root.bind("<Escape>", lambda event: close())
    root.protocol("WM_DELETE_WINDOW", close)
    root.update_idletasks()
    x = max(0, (root.winfo_screenwidth() - root.winfo_width()) // 2)
    y = max(0, (root.winfo_screenheight() - root.winfo_height()) // 3)
    root.geometry(f"+{x}+{y}")
    root.lift()
    root.attributes("-topmost", True)
    root.after(250, lambda: root.attributes("-topmost", False))
    root.mainloop()


def _run_macos_dialog(
    hotkeys: dict[str, str],
    on_save: SaveHotkeys,
    language_favorites: object = None,
) -> None:
    import AppKit

    AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    platform = "darwin"
    alert = AppKit.NSAlert.alloc().init()
    alert.setMessageText_("Hotkey settings")
    alert.setInformativeText_(
        "Choose a shortcut or type one, such as Control + Option + Space."
    )
    alert.addButtonWithTitle_("Save hotkeys")
    alert.addButtonWithTitle_("Cancel")

    width = 500
    row_height = 34
    view = AppKit.NSView.alloc().initWithFrame_(
        AppKit.NSMakeRect(0, 0, width, row_height * len(HOTKEY_ACTIONS))
    )
    fields: dict[str, Any] = {}
    for index, action in enumerate(HOTKEY_ACTIONS):
        y = row_height * (len(HOTKEY_ACTIONS) - index - 1)
        label_view = AppKit.NSTextField.labelWithString_(
            action.label_for_favorites(language_favorites)
        )
        label_view.setFrame_(AppKit.NSMakeRect(0, y + 5, 185, 22))
        view.addSubview_(label_view)

        field = AppKit.NSComboBox.alloc().initWithFrame_(
            AppKit.NSMakeRect(195, y, 305, 26)
        )
        field.addItemsWithObjectValues_(
            _choice_labels(platform, hotkeys, action)
        )
        field.setStringValue_(
            display_hotkey(
                hotkeys.get(action.setting_key),
                platform=platform,
            )
        )
        view.addSubview_(field)
        fields[action.setting_key] = field

    alert.setAccessoryView_(view)
    while True:
        response = alert.runModal()
        if response != AppKit.NSAlertFirstButtonReturn:
            return
        try:
            on_save(
                {key: str(field.stringValue()) for key, field in fields.items()}
            )
            return
        except Exception as exc:
            error = AppKit.NSAlert.alloc().init()
            error.setAlertStyle_(AppKit.NSAlertStyleWarning)
            error.setMessageText_("Hotkeys were not changed")
            error.setInformativeText_(
                str(exc) or "The hotkey settings could not be saved."
            )
            error.addButtonWithTitle_("Try again")
            error.runModal()
