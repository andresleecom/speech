from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from typing import Any

from .branding import APP_NAME
from .languages import (
    AUTO_LANGUAGE_MODE,
    filter_language_choice_labels,
    language_choice_label,
    language_choice_labels,
    normalize_language_mode,
)
from .logger import get_logger

SaveLanguage = Callable[[str], None]

_ACCENT = "#DB4241"


class LanguageSettingsWindow:
    """Open one native language picker without blocking the tray event loop."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._is_open = False
        self._logger = get_logger(__name__)

    def show(self, language_mode: str, on_save: SaveLanguage) -> None:
        with self._lock:
            if self._is_open:
                return
            self._is_open = True

        mode = normalize_language_mode(language_mode) or AUTO_LANGUAGE_MODE
        if sys.platform == "darwin":
            self._show_macos(mode, on_save)
            return

        threading.Thread(
            target=self._run_tk,
            args=(mode, on_save),
            name="winwhisper-language-settings",
            daemon=True,
        ).start()

    def _mark_closed(self) -> None:
        with self._lock:
            self._is_open = False

    def _run_tk(self, language_mode: str, on_save: SaveLanguage) -> None:
        try:
            _run_tk_dialog(language_mode, on_save)
        except Exception:
            self._logger.exception("Language settings window failed.")
        finally:
            self._mark_closed()

    def _show_macos(self, language_mode: str, on_save: SaveLanguage) -> None:
        try:
            from Foundation import NSOperationQueue

            def present() -> None:
                try:
                    _run_macos_dialog(language_mode, on_save)
                except Exception:
                    self._logger.exception("macOS language settings window failed.")
                finally:
                    self._mark_closed()

            NSOperationQueue.mainQueue().addOperationWithBlock_(present)
        except Exception:
            self._logger.exception("Could not schedule the macOS language settings.")
            self._mark_closed()


def _run_tk_dialog(language_mode: str, on_save: SaveLanguage) -> None:
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title(f"{APP_NAME} Settings - Language")
    root.resizable(False, False)
    root.configure(bg="#F7F7F8")

    frame = tk.Frame(root, bg="#F7F7F8", padx=24, pady=22)
    frame.grid(row=0, column=0, sticky="nsew")
    tk.Label(
        frame,
        text="Dictation language",
        bg="#F7F7F8",
        fg="#1E1E22",
        font=("Segoe UI", 16, "bold"),
        anchor="w",
    ).grid(row=0, column=0, sticky="w")
    tk.Label(
        frame,
        text="Type a language name or choose one. Auto-detect is the default.",
        bg="#F7F7F8",
        fg="#62626A",
        font=("Segoe UI", 9),
        anchor="w",
    ).grid(row=1, column=0, sticky="w", pady=(4, 14))

    selected = tk.StringVar(value=language_choice_label(language_mode))
    choice = ttk.Combobox(
        frame,
        textvariable=selected,
        values=language_choice_labels(),
        width=38,
    )
    choice.grid(row=2, column=0, sticky="ew")
    choice.focus_set()

    def filter_choices(event: Any = None) -> None:
        choice.configure(values=filter_language_choice_labels(selected.get()))

    choice.bind("<KeyRelease>", filter_choices)

    error = tk.StringVar(value="")
    tk.Label(
        frame,
        textvariable=error,
        bg="#F7F7F8",
        fg=_ACCENT,
        font=("Segoe UI", 9),
        justify="left",
        wraplength=360,
        anchor="w",
    ).grid(row=3, column=0, sticky="ew", pady=(10, 0))

    actions = tk.Frame(frame, bg="#F7F7F8")
    actions.grid(row=4, column=0, sticky="e", pady=(16, 0))

    def save() -> None:
        mode = normalize_language_mode(selected.get())
        if mode is None:
            error.set("Choose a supported language or Auto-detect.")
            return
        try:
            on_save(mode)
        except Exception as exc:
            error.set(str(exc) or "The language could not be saved.")
            return
        root.destroy()

    tk.Button(
        actions,
        text="Cancel",
        command=root.destroy,
        padx=14,
        pady=7,
        relief="flat",
        bg="#E7E7EA",
        activebackground="#DCDCE0",
        fg="#303036",
    ).pack(side="left", padx=(0, 8))
    tk.Button(
        actions,
        text="Save language",
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
    root.bind("<Escape>", lambda event: root.destroy())
    root.update_idletasks()
    x = max(0, (root.winfo_screenwidth() - root.winfo_width()) // 2)
    y = max(0, (root.winfo_screenheight() - root.winfo_height()) // 3)
    root.geometry(f"+{x}+{y}")
    root.lift()
    root.attributes("-topmost", True)
    root.after(250, lambda: root.attributes("-topmost", False))
    root.mainloop()


def _run_macos_dialog(language_mode: str, on_save: SaveLanguage) -> None:
    import AppKit

    AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    alert = AppKit.NSAlert.alloc().init()
    alert.setMessageText_("Dictation language")
    alert.setInformativeText_(
        "Type a language name or choose one. Auto-detect is the default."
    )
    alert.addButtonWithTitle_("Save language")
    alert.addButtonWithTitle_("Cancel")

    view = AppKit.NSView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, 420, 30))
    choice = AppKit.NSComboBox.alloc().initWithFrame_(
        AppKit.NSMakeRect(0, 0, 420, 26)
    )
    choice.setEditable_(True)
    if hasattr(choice, "setCompletes_"):
        choice.setCompletes_(True)
    choice.addItemsWithObjectValues_(language_choice_labels())
    choice.setStringValue_(language_choice_label(language_mode))
    view.addSubview_(choice)
    alert.setAccessoryView_(view)

    while True:
        response = alert.runModal()
        if response != AppKit.NSAlertFirstButtonReturn:
            return
        mode = normalize_language_mode(str(choice.stringValue()))
        if mode is None:
            _show_macos_error("Choose a supported language or Auto-detect.")
            continue
        try:
            on_save(mode)
            return
        except Exception as exc:
            _show_macos_error(str(exc) or "The language could not be saved.")


def _show_macos_error(message: str) -> None:
    import AppKit

    error = AppKit.NSAlert.alloc().init()
    error.setAlertStyle_(AppKit.NSAlertStyleWarning)
    error.setMessageText_("Language was not changed")
    error.setInformativeText_(message)
    error.addButtonWithTitle_("Try again")
    error.runModal()
