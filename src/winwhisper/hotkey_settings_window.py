from __future__ import annotations

import sys
import threading
from collections.abc import Callable, Mapping
from typing import Any

from .branding import APP_NAME, apply_tk_app_icon
from .hotkey_actions import HOTKEY_ACTIONS, HotkeyAction
from .hotkey_settings import combo_from_key_event, display_hotkey
from .logger import get_logger

SaveHotkeys = Callable[[dict[str, str]], None]
CaptureHook = Callable[[], None]

_ACCENT = "#DB4241"
_MUTED = "#62626A"
_SURFACE = "#F7F7F8"


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
        on_capture_begin: CaptureHook | None = None,
        on_capture_end: CaptureHook | None = None,
    ) -> None:
        with self._lock:
            if self._is_open:
                return
            self._is_open = True

        snapshot = dict(hotkeys)
        favorites_snapshot = language_favorites
        if sys.platform == "darwin":
            self._show_macos(
                snapshot,
                on_save,
                favorites_snapshot,
                on_capture_begin=on_capture_begin,
                on_capture_end=on_capture_end,
            )
            return

        threading.Thread(
            target=self._run_tk,
            args=(
                snapshot,
                on_save,
                favorites_snapshot,
                on_capture_begin,
                on_capture_end,
            ),
            name="winwhisper-hotkey-settings",
            daemon=True,
        ).start()

    def _mark_closed(self) -> None:
        with self._lock:
            self._is_open = False

    def _run_capture_hook(self, hook: CaptureHook | None, label: str) -> None:
        if hook is None:
            return
        try:
            hook()
        except Exception:
            self._logger.exception("Hotkey settings %s hook failed.", label)

    def _run_tk(
        self,
        hotkeys: dict[str, str],
        on_save: SaveHotkeys,
        language_favorites: object,
        on_capture_begin: CaptureHook | None = None,
        on_capture_end: CaptureHook | None = None,
    ) -> None:
        self._run_capture_hook(on_capture_begin, "capture begin")
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
            self._run_capture_hook(on_capture_end, "capture end")
            self._mark_closed()

    def _show_macos(
        self,
        hotkeys: dict[str, str],
        on_save: SaveHotkeys,
        language_favorites: object,
        on_capture_begin: CaptureHook | None = None,
        on_capture_end: CaptureHook | None = None,
    ) -> None:
        self._run_capture_hook(on_capture_begin, "capture begin")
        try:
            from Foundation import NSOperationQueue

            def present() -> None:
                try:
                    _run_macos_dialog(hotkeys, on_save, language_favorites)
                except Exception:
                    self._logger.exception("macOS hotkey settings window failed.")
                finally:
                    self._run_capture_hook(on_capture_end, "capture end")
                    self._mark_closed()

            NSOperationQueue.mainQueue().addOperationWithBlock_(present)
        except Exception:
            self._logger.exception("Could not schedule the macOS settings window.")
            self._run_capture_hook(on_capture_end, "capture end")
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
    status_setter: Callable[..., None],
    active_capture: dict[str, Any],
) -> Callable[[], None]:
    """Build the per-row Record handler.

    Mouse and keyboard capture run together; whichever reports a combo first
    wins. Capture callbacks from the mouse listener arrive on another thread,
    so every UI touch is bounced back through ``root.after``.
    """
    from .hotkeys import windows_modifier_state
    from .mouse_capture import MouseCapture

    def stop_mouse(session: dict[str, Any] | None) -> None:
        if session is None:
            return
        mouse = session.get("mouse")
        session["mouse"] = None
        if mouse is not None:
            try:
                mouse.cancel()
            except Exception:
                pass

    def restore() -> None:
        button.configure(text="Record")
        session = captures.pop(setting_key, None)
        if active_capture.get("key") == setting_key:
            active_capture["key"] = None
            try:
                root.unbind("<KeyPress>")
            except Exception:
                pass
        stop_mouse(session)

    def apply_combo(combo: str) -> None:
        value.set(display_hotkey(combo, platform=platform))
        status_setter("")
        restore()

    def on_captured(combo: str) -> None:
        def apply() -> None:
            session = captures.get(setting_key)
            if session is None or session.get("done"):
                return
            session["done"] = True
            apply_combo(combo)

        root.after(0, apply)

    def on_cancelled() -> None:
        def apply() -> None:
            session = captures.get(setting_key)
            if session is None or session.get("done"):
                return
            status_setter(
                "No input detected. Try again, or choose a shortcut from the list."
            )
            restore()

        root.after(0, apply)

    def on_key_press(event: Any) -> str | None:
        if active_capture.get("key") != setting_key:
            return None
        session = captures.get(setting_key)
        if session is None or session.get("done"):
            return None
        keysym = str(getattr(event, "keysym", "") or "")
        if keysym.lower() == "escape":
            session["done"] = True
            status_setter("")
            restore()
            return "break"
        extra: tuple[str, ...] = ()
        if platform == "win32":
            try:
                # Tk state has Ctrl/Shift/Alt; the Win key only shows up here.
                extra = tuple(
                    name for name in windows_modifier_state() if name == "cmd"
                )
            except Exception:
                extra = ()
        combo = combo_from_key_event(
            keycode=int(getattr(event, "keycode", 0) or 0),
            keysym=keysym,
            state=int(getattr(event, "state", 0) or 0),
            platform=platform,
            extra_modifiers=extra,
        )
        if combo is None:
            return "break"
        session["done"] = True
        stop_mouse(session)
        apply_combo(combo)
        return "break"

    def start() -> None:
        existing = captures.get(setting_key)
        if existing is not None:
            existing["done"] = True
            restore()
            return

        # Only one row records at a time.
        previous_key = active_capture.get("key")
        if previous_key is not None and previous_key in captures:
            previous = captures.get(previous_key)
            if previous is not None:
                previous["done"] = True
                previous_button = previous.get("button")
                if previous_button is not None:
                    previous_button.configure(text="Record")
                stop_mouse(previous)
            captures.pop(previous_key, None)
            active_capture["key"] = None
            try:
                root.unbind("<KeyPress>")
            except Exception:
                pass

        capture: Any = None
        try:
            capture = MouseCapture(on_captured, on_cancelled)
            capture.start()
        except Exception:
            get_logger(__name__).exception("Mouse capture could not start.")
            capture = None
        captures[setting_key] = {
            "mouse": capture,
            "button": button,
            "done": False,
        }
        active_capture["key"] = setting_key
        root.bind("<KeyPress>", on_key_press)
        button.configure(text="Press keys...")
        status_setter(
            "Press a shortcut or mouse button now. Escape cancels. "
            "Left click needs a modifier.",
            is_error=False,
        )

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
    root.title(f"{APP_NAME} Settings - Hotkeys")
    root.resizable(False, False)
    root.configure(bg=_SURFACE)
    apply_tk_app_icon(root)

    frame = tk.Frame(root, bg=_SURFACE, padx=24, pady=22)
    frame.grid(row=0, column=0, sticky="nsew")

    tk.Label(
        frame,
        text="Hotkey settings",
        bg=_SURFACE,
        fg="#1E1E22",
        font=("Segoe UI", 16, "bold"),
        anchor="w",
    ).grid(row=0, column=0, columnspan=3, sticky="w")
    tk.Label(
        frame,
        text=(
            "Choose a shortcut, or press Record and then the keys or a mouse "
            "button."
        ),
        bg=_SURFACE,
        fg=_MUTED,
        font=("Segoe UI", 9),
        anchor="w",
    ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 18))

    status = tk.StringVar(value="")
    status_label = tk.Label(
        frame,
        textvariable=status,
        bg=_SURFACE,
        fg=_ACCENT,
        font=("Segoe UI", 9),
        justify="left",
        wraplength=450,
        anchor="w",
    )

    def set_status(message: str, *, is_error: bool = True) -> None:
        # Hints and failures share the one line, so its color has to say which
        # of the two the reader is looking at.
        status.set(message)
        status_label.configure(fg=_ACCENT if is_error else _MUTED)

    values: dict[str, tk.StringVar] = {}
    captures: dict[str, Any] = {}
    active_capture: dict[str, Any] = {"key": None}
    for row, action in enumerate(HOTKEY_ACTIONS, start=2):
        tk.Label(
            frame,
            text=action.label_for_favorites(language_favorites),
            bg=_SURFACE,
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
                status_setter=set_status,
                active_capture=active_capture,
            )
        )

    status_label.grid(
        row=len(HOTKEY_ACTIONS) + 2,
        column=0,
        columnspan=3,
        sticky="ew",
        pady=(12, 4),
    )

    actions = tk.Frame(frame, bg=_SURFACE)
    actions.grid(
        row=len(HOTKEY_ACTIONS) + 3,
        column=0,
        columnspan=3,
        sticky="e",
        pady=(12, 0),
    )

    def close() -> None:
        # Leaving a capture running would keep a mouse listener alive with no
        # window to report into.
        for key in list(captures):
            session = captures.pop(key, None)
            if session is None:
                continue
            mouse = session.get("mouse") if isinstance(session, dict) else session
            if mouse is not None:
                try:
                    mouse.cancel()
                except Exception:
                    pass
        active_capture["key"] = None
        try:
            root.unbind("<KeyPress>")
        except Exception:
            pass
        root.destroy()

    def save() -> None:
        try:
            on_save({key: value.get() for key, value in values.items()})
        except Exception as exc:
            set_status(str(exc) or "The hotkey settings could not be saved.")
            return
        close()

    def on_escape(_event: Any) -> None:
        if active_capture.get("key") is not None:
            key = active_capture["key"]
            session = captures.get(key)
            if session is not None:
                button = session.get("button")
                if button is not None:
                    button.configure(text="Record")
                mouse = session.get("mouse")
                if mouse is not None:
                    try:
                        mouse.cancel()
                    except Exception:
                        pass
            captures.pop(key, None)
            active_capture["key"] = None
            try:
                root.unbind("<KeyPress>")
            except Exception:
                pass
            set_status("")
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
    root.bind("<Escape>", on_escape)
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
        "Choose a shortcut or type one, such as Control + Shift + Space."
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
