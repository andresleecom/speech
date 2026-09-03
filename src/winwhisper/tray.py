from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable
from typing import Any

from . import __version__
from . import startup as startup_module
from .audio_inputs import (
    AudioInputDevice,
    AudioInputDeviceError,
    PhysicalInputDevice,
    SYSTEM_DEFAULT_INPUT_LABEL,
    audio_input_device_label,
    group_physical_input_devices,
    input_device_signature,
    list_audio_input_devices,
    refresh_audio_device_table,
)
from .branding import APP_NAME
from .hotkey_settings import display_hotkey
from .languages import language_name, tray_language_modes

_STATUS_COLORS = {
    "Idle": (128, 128, 128, 255),
    "Recording": (220, 38, 38, 255),
    "Testing microphone": (14, 116, 144, 255),
    "Transcribing": (245, 158, 11, 255),
    "Pasting": (37, 99, 235, 255),
    "Error": (127, 29, 29, 255),
    "Downloading model...": (14, 116, 144, 255),
}
_TOOLTIP_MAX_LENGTH = 120
_MAX_PENDING_NOTIFICATIONS = 20
_INPUT_DEVICE_POLL_SECONDS = 2.0
_logger = logging.getLogger(__name__)


class TrayApp:
    """System tray UI.

    pystray's Win32 icon is not thread-safe. All Icon mutations go through
    `_ui_lock` so worker threads (dictation, updates, diagnostics) never race
    the icon loop or each other on `icon` / `title` / `notify` / `update_menu`.
    """

    def __init__(self, controller: Any) -> None:
        self._controller = controller
        self._icon: Any | None = None
        self._status = "Idle"
        self._microphone_label = SYSTEM_DEFAULT_INPUT_LABEL
        self._microphone_item_cls: Any | None = None
        self._ui_lock = threading.RLock()
        self._pending_notifications: list[tuple[str, str]] = []
        self._input_device_poll_timer: threading.Timer | None = None
        self._last_input_device_signature: tuple[str, ...] | None = None

    def run(self) -> None:
        from pystray import Icon, Menu, MenuItem

        if sys.platform.startswith("linux") and not Icon.HAS_MENU:
            raise RuntimeError("The selected Linux tray backend does not support menus")

        with self._ui_lock:
            self._icon = Icon(
                APP_NAME,
                self._make_icon_image(),
                self._tooltip(),
                self._make_menu(Menu, MenuItem),
            )
            icon = self._icon
        icon.run(setup=self._on_icon_ready)

    def stop(self) -> None:
        with self._ui_lock:
            timer = self._input_device_poll_timer
            self._input_device_poll_timer = None
            self._last_input_device_signature = None
            icon = self._icon
            self._icon = None
        if timer is not None:
            timer.cancel()
        if icon is None:
            return
        try:
            icon.stop()
        except Exception:
            pass

    def set_status(self, status: str) -> None:
        with self._ui_lock:
            self._status = status
            icon = self._icon
            if icon is None:
                return
            try:
                icon.title = self._tooltip()
                icon.icon = self._make_icon_image()
                self._update_menu_unlocked()
            except Exception:
                pass

    def set_microphone_label(self, label: str) -> None:
        with self._ui_lock:
            self._microphone_label = str(label).strip() or SYSTEM_DEFAULT_INPUT_LABEL
            icon = self._icon
            if icon is None:
                return
            try:
                icon.title = self._tooltip()
            except Exception:
                pass

    def notify(self, title: str, message: str) -> None:
        with self._ui_lock:
            icon = self._icon
            if icon is None:
                if len(self._pending_notifications) < _MAX_PENDING_NOTIFICATIONS:
                    self._pending_notifications.append((title, message))
                return
            try:
                icon.notify(message, title)
            except Exception:
                pass

    def refresh_menu(self) -> None:
        self._update_menu()

    def _on_icon_ready(self, icon: Any) -> None:
        # Win32 balloons need a visible icon; pystray's default setup only
        # sets visible when no custom setup is provided.
        icon.visible = True
        with self._ui_lock:
            pending = list(self._pending_notifications)
            self._pending_notifications.clear()
        for title, message in pending:
            self.notify(title, message)
        self._start_input_device_polling()

    def _start_input_device_polling(self) -> None:
        signature = input_device_signature()
        if signature is None:
            return
        with self._ui_lock:
            if self._icon is None:
                return
            self._last_input_device_signature = signature
            self._schedule_input_device_poll_unlocked()

    def _schedule_input_device_poll_unlocked(self) -> None:
        timer = threading.Timer(
            _INPUT_DEVICE_POLL_SECONDS,
            self._poll_input_devices,
        )
        timer.daemon = True
        self._input_device_poll_timer = timer
        timer.start()

    def _poll_input_devices(self) -> None:
        signature = input_device_signature()
        with self._ui_lock:
            self._input_device_poll_timer = None
            if self._icon is None or signature is None:
                return
            changed = signature != self._last_input_device_signature
            self._last_input_device_signature = signature

        if changed:
            refresh_audio_device_table()
            self.refresh_menu()
            _logger.info("Input devices changed; microphone menu refreshed.")

        with self._ui_lock:
            if self._icon is not None:
                self._schedule_input_device_poll_unlocked()

    def _make_menu(self, menu_cls: Any, item_cls: Any) -> Any:
        return menu_cls(
            item_cls(
                f"Speech {__version__}",
                lambda icon, item: None,
                enabled=False,
            ),
            item_cls(self._toggle_recording_label, self._on_toggle),
            item_cls(
                self._wake_word_label(),
                self._on_toggle_wake_word,
                checked=lambda item: self._current_wake_word_enabled(),
            ),
            item_cls(
                "Language",
                self._make_language_menu(menu_cls, item_cls),
            ),
            item_cls(
                "Microphone",
                self._make_microphone_menu(menu_cls, item_cls),
            ),
            item_cls(
                "Cleanup",
                menu_cls(
                    self._radio_item(
                        item_cls,
                        "None",
                        "none",
                        self._current_cleanup,
                        self._select_cleanup,
                    ),
                    self._radio_item(
                        item_cls,
                        "Basic",
                        "basic",
                        self._current_cleanup,
                        self._select_cleanup,
                    ),
                    self._radio_item(
                        item_cls,
                        "LLM",
                        "llm",
                        self._current_cleanup,
                        self._select_cleanup,
                    ),
                ),
            ),
            item_cls("Hotkey Settings...", self._on_hotkey_settings),
            item_cls(
                "Permissions...",
                self._on_permissions,
                visible=sys.platform == "darwin",
            ),
            item_cls("Open Settings File", self._on_open_settings),
            item_cls("Open Log Folder", self._on_open_log_folder),
            item_cls(
                "Check for Updates",
                self._on_check_updates,
                visible=sys.platform == "win32",
            ),
            item_cls("Diagnostics", self._on_diagnostics),
            item_cls(
                "Start at login",
                self._on_toggle_startup,
                checked=lambda item: self._startup_is_enabled(),
                visible=sys.platform == "win32",
            ),
            item_cls("Exit", self._on_exit),
        )

    def _make_language_menu(self, menu_cls: Any, item_cls: Any) -> Any:
        items = [
            self._radio_item(
                item_cls,
                "Auto",
                "auto",
                self._current_language,
                self._select_language,
            )
        ]
        for mode in tray_language_modes(
            self._current_language(),
            getattr(self._controller.settings, "language_favorites", ()),
        ):
            items.append(
                self._radio_item(
                    item_cls,
                    language_name(mode),
                    mode,
                    self._current_language,
                    self._select_language,
                )
            )
        items.append(item_cls("Language Settings...", self._on_language_settings))
        return menu_cls(*items)

    def _make_microphone_menu(self, menu_cls: Any, item_cls: Any) -> Any:
        self._microphone_item_cls = item_cls
        return menu_cls(self._microphone_menu_items)

    def _microphone_menu_items(self) -> tuple[Any, ...]:
        item_cls = self._microphone_item_cls
        if item_cls is None:
            return ()
        items = [
            item_cls(
                SYSTEM_DEFAULT_INPUT_LABEL,
                self._selection_action(
                    (None, None), self._select_audio_input_selection
                ),
                checked=lambda item: self._system_default_selected(),
                radio=True,
            )
        ]
        try:
            devices = list_audio_input_devices()
        except AudioInputDeviceError:
            devices = ()
        groups = group_physical_input_devices(devices)

        if groups:
            for group in groups:
                items.append(
                    item_cls(
                        group.label,
                        self._selection_action(
                            (group.preferred.name, group.preferred.host_api),
                            self._select_audio_input_selection,
                        ),
                        checked=self._device_checked(group, groups),
                        radio=True,
                    )
                )
        else:
            items.append(
                item_cls("No microphone available", lambda icon, item: None, enabled=False)
            )

        if self._saved_microphone_missing(groups):
            items.append(
                item_cls(
                    self._unavailable_microphone_label(devices),
                    lambda icon, item: None,
                    enabled=False,
                )
            )
        items.append(item_cls("Test Microphone", self._on_test_microphone))
        return tuple(items)

    def _radio_item(
        self,
        item_cls: Any,
        label: str,
        value: Any,
        current: Callable[[], Any],
        select: Callable[[Any], None],
    ) -> Any:
        return item_cls(
            label,
            self._selection_action(value, select),
            checked=lambda item: current() == value,
            radio=True,
        )

    def _selection_action(
        self,
        value: Any,
        select: Callable[[Any], None],
    ) -> Callable[[Any, Any], None]:
        def action(icon: Any, item: Any) -> None:
            select(value)
            with self._ui_lock:
                self._update_menu_unlocked()

        return action

    def _on_toggle(self, icon: Any, item: Any) -> None:
        self._controller.toggle()

    def _toggle_recording_label(self, item: Any | None = None) -> str:
        return f"Start/Stop Recording ({self._toggle_hotkey_display()})"

    def _toggle_hotkey_display(self) -> str:
        hotkeys = getattr(self._controller.settings, "hotkeys", None) or {}
        combo = hotkeys.get("toggle_recording")
        return display_hotkey(combo)

    def _startup_is_enabled(self) -> bool:
        return startup_module.is_enabled()

    def _on_toggle_startup(self, icon: Any, item: Any) -> None:
        try:
            if startup_module.is_enabled():
                startup_module.disable()
            else:
                exe = startup_module.installed_executable()
                if exe is None:
                    self._controller.notify(
                        APP_NAME,
                        "Start at login is available in the installed Speech app.",
                    )
                    return
                startup_module.enable(exe)
        except Exception as exc:
            self._controller.notify(
                APP_NAME,
                str(exc) or "Start at login could not be updated.",
            )
        self._update_menu()

    def _on_toggle_wake_word(self, icon: Any, item: Any) -> None:
        self._controller.set_wake_word_enabled(not self._current_wake_word_enabled())

    def _current_wake_word_enabled(self) -> bool:
        return bool(getattr(self._controller.settings, "wake_word_enabled", False))

    def _wake_word_label(self) -> str:
        phrases = getattr(self._controller.settings, "wake_phrases", None) or [
            "hey speech"
        ]
        label = " / ".join(f'"{phrase}"' for phrase in phrases)
        return f"Wake word ({label})"

    def _on_open_settings(self, icon: Any, item: Any) -> None:
        self._controller.open_settings_file()

    def _on_open_log_folder(self, icon: Any, item: Any) -> None:
        self._controller.open_log_folder()

    def _on_hotkey_settings(self, icon: Any, item: Any) -> None:
        self._controller.open_hotkey_settings()

    def _on_permissions(self, icon: Any, item: Any) -> None:
        self._controller.open_permission_setup()

    def _on_language_settings(self, icon: Any, item: Any) -> None:
        self._controller.open_language_settings()

    def _on_test_microphone(self, icon: Any, item: Any) -> None:
        try:
            self._controller.start_microphone_test()
        except Exception as exc:
            self._controller.notify(
                APP_NAME,
                str(exc) or "Microphone test could not start.",
            )

    def _on_diagnostics(self, icon: Any, item: Any) -> None:
        self._controller.run_diagnostics()

    def _on_check_updates(self, icon: Any, item: Any) -> None:
        self._controller.check_for_updates()

    def _on_exit(self, icon: Any, item: Any) -> None:
        self._controller.exit_app()

    def _select_language(self, mode: str) -> None:
        self._controller.set_language_mode(mode)

    def _select_cleanup(self, mode: str) -> None:
        self._controller.set_cleanup_mode(mode)

    def _select_audio_input_device(self, device: int | None) -> None:
        try:
            self._controller.set_audio_input_device(device)
        except Exception as exc:
            self._controller.notify(
                APP_NAME,
                str(exc) or "Microphone setting could not be saved.",
            )

    def _select_audio_input_selection(
        self, selection: tuple[str | None, str | None]
    ) -> None:
        try:
            self._controller.set_audio_input_selection(*selection)
        except Exception as exc:
            self._controller.notify(
                APP_NAME,
                str(exc) or "Microphone setting could not be saved.",
            )

    def _current_language(self) -> str:
        return str(self._controller.settings.language_mode)

    def _current_cleanup(self) -> str:
        return str(self._controller.settings.cleanup_mode)

    def _current_audio_input_device(self) -> int | None:
        return getattr(self._controller.settings, "audio_input_device", None)

    def _saved_microphone_name(self) -> str | None:
        return getattr(self._controller.settings, "audio_input_device_name", None)

    def _saved_microphone_host_api(self) -> str | None:
        return getattr(self._controller.settings, "audio_input_device_host_api", None)

    def _system_default_selected(self) -> bool:
        return (
            self._saved_microphone_name() is None
            and self._current_audio_input_device() is None
        )

    def _device_matches_saved(
        self,
        group: PhysicalInputDevice,
        groups: tuple[PhysicalInputDevice, ...],
    ) -> bool:
        saved_name = self._saved_microphone_name()
        if saved_name is not None:
            saved_host_api = self._saved_microphone_host_api() or ""
            exact_group = next(
                (
                    candidate
                    for candidate in groups
                    if any(
                        row.name == saved_name and row.host_api == saved_host_api
                        for row in candidate.rows
                    )
                ),
                None,
            )
            if exact_group is not None:
                return group is exact_group
            return any(row.name == saved_name for row in group.rows)
        selected = self._current_audio_input_device()
        return selected is not None and any(
            row.index == selected for row in group.rows
        )

    def _device_checked(
        self,
        group: PhysicalInputDevice,
        groups: tuple[PhysicalInputDevice, ...],
    ) -> Callable[[Any], bool]:
        def checked(item: Any) -> bool:
            return self._device_matches_saved(group, groups)

        return checked

    def _saved_microphone_missing(
        self, groups: tuple[PhysicalInputDevice, ...]
    ) -> bool:
        saved_name = self._saved_microphone_name()
        if saved_name is not None:
            return not any(
                self._device_matches_saved(group, groups) for group in groups
            )
        selected = self._current_audio_input_device()
        if selected is None:
            return False
        return not any(
            row.index == selected for group in groups for row in group.rows
        )

    def _unavailable_microphone_label(
        self, devices: tuple[AudioInputDevice, ...]
    ) -> str:
        saved_name = self._saved_microphone_name()
        selected = self._current_audio_input_device()
        if saved_name is not None:
            return f"{saved_name} (unavailable)"
        return audio_input_device_label(selected, devices)

    def _tooltip(self) -> str:
        parts = [APP_NAME, self._status, self._microphone_label]
        if self._status == "Idle":
            parts.append(self._toggle_hotkey_display())
        tooltip = " - ".join(parts)
        if len(tooltip) <= _TOOLTIP_MAX_LENGTH:
            return tooltip
        return tooltip[: _TOOLTIP_MAX_LENGTH - 3] + "..."

    def _make_icon_image(self) -> Any:
        from PIL import Image, ImageDraw

        color = _STATUS_COLORS.get(self._status, _STATUS_COLORS["Idle"])
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((8, 8, 56, 56), fill=color)
        draw.ellipse((8, 8, 56, 56), outline=(255, 255, 255, 255), width=3)
        return image

    def _update_menu(self) -> None:
        with self._ui_lock:
            self._update_menu_unlocked()

    def _update_menu_unlocked(self) -> None:
        icon = self._icon
        if icon is None:
            return
        try:
            icon.update_menu()
        except Exception:
            pass
