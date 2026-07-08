from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from .branding import APP_NAME

_STATUS_COLORS = {
    "Idle": (128, 128, 128, 255),
    "Recording": (220, 38, 38, 255),
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
            if icon is None:
                return
        icon.stop()

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

    def _make_menu(self, menu_cls: Any, item_cls: Any) -> Any:
        return menu_cls(
            item_cls("Start/Stop Recording", self._on_toggle),
            item_cls(
                "Language",
                menu_cls(
                    self._radio_item(
                        item_cls,
                        "Auto",
                        "auto",
                        self._current_language,
                        self._select_language,
                    ),
                    self._radio_item(
                        item_cls,
                        "English",
                        "en",
                        self._current_language,
                        self._select_language,
                    ),
                    self._radio_item(
                        item_cls,
                        "Spanish",
                        "es",
                        self._current_language,
                        self._select_language,
                    ),
                ),
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
            item_cls("Open Settings File", self._on_open_settings),
            item_cls("Check for Updates", self._on_check_updates),
            item_cls("Diagnostics", self._on_diagnostics),
            item_cls("Exit", self._on_exit),
        )

    def _radio_item(
        self,
        item_cls: Any,
        label: str,
        value: str,
        current: Callable[[], str],
        select: Callable[[str], None],
    ) -> Any:
        return item_cls(
            label,
            self._selection_action(value, select),
            checked=lambda item: current() == value,
            radio=True,
        )

    def _selection_action(
        self,
        value: str,
        select: Callable[[str], None],
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

    def _current_language(self) -> str:
        return str(self._controller.settings.language_mode)

    def _current_cleanup(self) -> str:
        return str(self._controller.settings.cleanup_mode)

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
