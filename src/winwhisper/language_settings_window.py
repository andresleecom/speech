from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from typing import Any

from .branding import APP_NAME
from .languages import (
    AUTO_LANGUAGE_MODE,
    DEFAULT_LANGUAGE_FAVORITES,
    filter_language_choice_labels,
    language_choice_label,
    language_choice_labels,
    normalize_language_favorites,
    normalize_language_mode,
)
from .logger import get_logger

SaveLanguagePreferences = Callable[[str, list[str | None]], None]

_ACCENT = "#DB4241"
_NOT_PINNED = "Not pinned"


class LanguageSettingsWindow:
    """Open one native language and favorite-language editor."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._is_open = False
        self._logger = get_logger(__name__)

    def show(
        self,
        language_mode: str,
        language_favorites: object,
        on_save: SaveLanguagePreferences,
    ) -> None:
        with self._lock:
            if self._is_open:
                return
            self._is_open = True

        mode = normalize_language_mode(language_mode) or AUTO_LANGUAGE_MODE
        try:
            favorites = normalize_language_favorites(language_favorites)
        except ValueError:
            favorites = DEFAULT_LANGUAGE_FAVORITES
        if sys.platform == "darwin":
            self._show_macos(mode, favorites, on_save)
            return

        threading.Thread(
            target=self._run_tk,
            args=(mode, favorites, on_save),
            name="winwhisper-language-settings",
            daemon=True,
        ).start()

    def _mark_closed(self) -> None:
        with self._lock:
            self._is_open = False

    def _run_tk(
        self,
        language_mode: str,
        language_favorites: tuple[str | None, ...],
        on_save: SaveLanguagePreferences,
    ) -> None:
        try:
            _run_tk_dialog(language_mode, language_favorites, on_save)
        except Exception:
            self._logger.exception("Language settings window failed.")
        finally:
            self._mark_closed()

    def _show_macos(
        self,
        language_mode: str,
        language_favorites: tuple[str | None, ...],
        on_save: SaveLanguagePreferences,
    ) -> None:
        try:
            from Foundation import NSOperationQueue

            def present() -> None:
                try:
                    _run_macos_dialog(language_mode, language_favorites, on_save)
                except Exception:
                    self._logger.exception("macOS language settings window failed.")
                finally:
                    self._mark_closed()

            NSOperationQueue.mainQueue().addOperationWithBlock_(present)
        except Exception:
            self._logger.exception("Could not schedule the macOS language settings.")
            self._mark_closed()


def _favorite_choice_labels() -> tuple[str, ...]:
    return (_NOT_PINNED, *language_choice_labels()[1:])


def _favorite_choice_label(language: str | None) -> str:
    if language is None:
        return _NOT_PINNED
    return language_choice_label(language)


def _filtered_choices(query: str, *, favorites: bool) -> tuple[str, ...]:
    choices = filter_language_choice_labels(query)
    if not favorites:
        return choices

    # A filtered result does not necessarily include Auto-detect at index zero,
    # so remove it by value rather than slicing it off.
    choices = tuple(choice for choice in choices if choice != "Auto-detect")
    normalized_query = query.strip().casefold()
    if not normalized_query or normalized_query in _NOT_PINNED.casefold():
        return (_NOT_PINNED, *choices)
    return choices


def _run_tk_dialog(
    language_mode: str,
    language_favorites: tuple[str | None, ...],
    on_save: SaveLanguagePreferences,
) -> None:
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title(f"{APP_NAME} Settings - Languages")
    root.resizable(False, False)
    root.configure(bg="#F7F7F8")

    frame = tk.Frame(root, bg="#F7F7F8", padx=24, pady=22)
    frame.grid(row=0, column=0, sticky="nsew")
    tk.Label(
        frame,
        text="Languages",
        bg="#F7F7F8",
        fg="#1E1E22",
        font=("Segoe UI", 16, "bold"),
        anchor="w",
    ).grid(row=0, column=0, columnspan=2, sticky="w")
    tk.Label(
        frame,
        text="Type a language name or choose one. Favorites can use quick hotkeys.",
        bg="#F7F7F8",
        fg="#62626A",
        font=("Segoe UI", 9),
        anchor="w",
    ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 14))

    tk.Label(
        frame,
        text="Dictation language",
        bg="#F7F7F8",
        fg="#2B2B30",
        font=("Segoe UI", 9),
        anchor="w",
    ).grid(row=2, column=0, sticky="w", padx=(0, 14), pady=4)
    selected = tk.StringVar(value=language_choice_label(language_mode))
    choice = ttk.Combobox(
        frame,
        textvariable=selected,
        values=language_choice_labels(),
        width=34,
    )
    choice.grid(row=2, column=1, sticky="ew", pady=4)
    choice.focus_set()

    favorite_values: list[tk.StringVar] = []
    for index, favorite in enumerate(language_favorites, start=1):
        row = index + 2
        tk.Label(
            frame,
            text=f"Favorite {index}",
            bg="#F7F7F8",
            fg="#2B2B30",
            font=("Segoe UI", 9),
            anchor="w",
        ).grid(row=row, column=0, sticky="w", padx=(0, 14), pady=4)
        value = tk.StringVar(value=_favorite_choice_label(favorite))
        favorite_values.append(value)
        favorite_choice = ttk.Combobox(
            frame,
            textvariable=value,
            values=_favorite_choice_labels(),
            width=34,
        )
        favorite_choice.grid(row=row, column=1, sticky="ew", pady=4)
        _bind_filter(favorite_choice, value, favorites=True)

    _bind_filter(choice, selected, favorites=False)

    error = tk.StringVar(value="")
    tk.Label(
        frame,
        textvariable=error,
        bg="#F7F7F8",
        fg=_ACCENT,
        font=("Segoe UI", 9),
        justify="left",
        wraplength=430,
        anchor="w",
    ).grid(row=6, column=0, columnspan=2, sticky="ew", pady=(10, 0))

    actions = tk.Frame(frame, bg="#F7F7F8")
    actions.grid(row=7, column=0, columnspan=2, sticky="e", pady=(16, 0))

    def save() -> None:
        mode = normalize_language_mode(selected.get())
        if mode is None:
            error.set("Choose a supported language or Auto-detect.")
            return
        try:
            favorites = list(
                normalize_language_favorites(
                    [value.get() for value in favorite_values]
                )
            )
        except ValueError as exc:
            error.set(str(exc))
            return
        try:
            on_save(mode, favorites)
        except Exception as exc:
            error.set(str(exc) or "The language preferences could not be saved.")
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
        text="Save languages",
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


def _bind_filter(choice: Any, value: Any, *, favorites: bool) -> None:
    def filter_choices(event: Any = None) -> None:
        choice.configure(values=_filtered_choices(value.get(), favorites=favorites))

    choice.bind("<KeyRelease>", filter_choices)


def _run_macos_dialog(
    language_mode: str,
    language_favorites: tuple[str | None, ...],
    on_save: SaveLanguagePreferences,
) -> None:
    import AppKit

    AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    alert = AppKit.NSAlert.alloc().init()
    alert.setMessageText_("Languages")
    alert.setInformativeText_(
        "Choose a dictation language and up to three favorites for quick hotkeys."
    )
    alert.addButtonWithTitle_("Save languages")
    alert.addButtonWithTitle_("Cancel")

    width = 460
    row_height = 34
    view = AppKit.NSView.alloc().initWithFrame_(
        AppKit.NSMakeRect(0, 0, width, row_height * 4)
    )
    active_field = _macos_combo_box(
        AppKit,
        AppKit.NSMakeRect(150, row_height * 3, 310, 26),
        language_choice_labels(),
        language_choice_label(language_mode),
    )
    active_label = AppKit.NSTextField.labelWithString_("Dictation language")
    active_label.setFrame_(AppKit.NSMakeRect(0, row_height * 3 + 5, 140, 22))
    view.addSubview_(active_label)
    view.addSubview_(active_field)

    favorite_fields: list[Any] = []
    for index, favorite in enumerate(language_favorites):
        y = row_height * (2 - index)
        label = AppKit.NSTextField.labelWithString_(f"Favorite {index + 1}")
        label.setFrame_(AppKit.NSMakeRect(0, y + 5, 140, 22))
        field = _macos_combo_box(
            AppKit,
            AppKit.NSMakeRect(150, y, 310, 26),
            _favorite_choice_labels(),
            _favorite_choice_label(favorite),
        )
        view.addSubview_(label)
        view.addSubview_(field)
        favorite_fields.append(field)

    alert.setAccessoryView_(view)
    while True:
        response = alert.runModal()
        if response != AppKit.NSAlertFirstButtonReturn:
            return
        mode = normalize_language_mode(str(active_field.stringValue()))
        if mode is None:
            _show_macos_error("Choose a supported language or Auto-detect.")
            continue
        try:
            favorites = list(
                normalize_language_favorites(
                    [str(field.stringValue()) for field in favorite_fields]
                )
            )
        except ValueError as exc:
            _show_macos_error(str(exc))
            continue
        try:
            on_save(mode, favorites)
            return
        except Exception as exc:
            _show_macos_error(str(exc) or "The language preferences could not be saved.")


def _macos_combo_box(AppKit: Any, frame: Any, values: tuple[str, ...], current: str) -> Any:
    choice = AppKit.NSComboBox.alloc().initWithFrame_(frame)
    choice.setEditable_(True)
    if hasattr(choice, "setCompletes_"):
        choice.setCompletes_(True)
    choice.addItemsWithObjectValues_(values)
    choice.setStringValue_(current)
    return choice


def _show_macos_error(message: str) -> None:
    import AppKit

    error = AppKit.NSAlert.alloc().init()
    error.setAlertStyle_(AppKit.NSAlertStyleWarning)
    error.setMessageText_("Languages were not changed")
    error.setInformativeText_(message)
    error.addButtonWithTitle_("Try again")
    error.runModal()
