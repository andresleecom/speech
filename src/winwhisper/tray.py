from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from typing import Any

from .audio_inputs import (
    AudioInputDeviceError,
    SYSTEM_DEFAULT_INPUT_LABEL,
    audio_input_device_label,
    list_audio_input_devices,
)
from .branding import APP_NAME
from .languages import language_name, tray_language_modes

_STATUS_COLORS = {
    "Idle": (128, 128, 128, 255),
    "Recording": (220, 38, 38, 255),
    "Testing microphone": (14, 116, 144, 255),
    "Transcribing": (245, 158, 11, 255),
    "Pasting": (37, 99, 235, 255),
    "Error": (127, 29, 29, 255),
}


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
        self._ui_lock = threading.RLock()

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
        icon.run()

    def stop(self) -> None:
        with self._ui_lock:
            icon = self._icon
            self._icon = None
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

    def notify(self, title: str, message: str) -> None:
        with self._ui_lock:
            icon = self._icon
            if icon is None:
                return
            try:
                icon.notify(message, title)
            except Exception:
                pass

    def refresh_menu(self) -> None:
        self._update_menu()

    def _make_menu(self, menu_cls: Any, item_cls: Any) -> Any:
        return menu_cls(
            item_cls("Start/Stop Recording", self._on_toggle),
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
            item_cls("Open Settings File", self._on_open_settings),
            item_cls(
                "Check for Updates",
                self._on_check_updates,
                visible=sys.platform == "win32",
            ),
            item_cls("Diagnostics", self._on_diagnostics),
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
        selected_device = self._current_audio_input_device()
        items = [
            self._radio_item(
                item_cls,
                SYSTEM_DEFAULT_INPUT_LABEL,
                None,
                self._current_audio_input_device,
                self._select_audio_input_device,
            )
        ]
        try:
            devices = list_audio_input_devices()
        except AudioInputDeviceError:
            devices = ()

        if devices:
            for device in devices:
                items.append(
                    self._radio_item(
                        item_cls,
                        device.choice_label,
                        device.index,
                        self._current_audio_input_device,
                        self._select_audio_input_device,
                    )
                )
        else:
            items.append(
                item_cls("No microphone available", lambda icon, item: None, enabled=False)
            )

        if selected_device is not None and not any(
            device.index == selected_device for device in devices
        ):
            items.append(
                item_cls(
                    audio_input_device_label(selected_device, devices),
                    lambda icon, item: None,
                    enabled=False,
                )
            )
        items.append(item_cls("Test Microphone", self._on_test_microphone))
        return menu_cls(*items)

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

    def _on_open_settings(self, icon: Any, item: Any) -> None:
        self._controller.open_settings_file()

    def _on_hotkey_settings(self, icon: Any, item: Any) -> None:
        self._controller.open_hotkey_settings()

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

    def _current_language(self) -> str:
        return str(self._controller.settings.language_mode)

    def _current_cleanup(self) -> str:
        return str(self._controller.settings.cleanup_mode)

    def _current_audio_input_device(self) -> int | None:
        return getattr(self._controller.settings, "audio_input_device", None)

    def _tooltip(self) -> str:
        return f"{APP_NAME} - {self._status}"

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
