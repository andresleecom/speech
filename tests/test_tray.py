import sys
import types

import pytest

import winwhisper.tray as tray_module
from winwhisper.audio_inputs import AudioInputDevice
from winwhisper.tray import TrayApp


class FakeMenu:
    def __init__(self, *items) -> None:
        self.items = items


class FakeMenuItem:
    def __init__(self, label, action, **kwargs) -> None:
        self.label = label
        self.action = action
        self.options = kwargs


class FakeController:
    def __init__(self) -> None:
        self.hotkey_settings_opened = False
        self.language_settings_opened = False
        self.settings = type(
            "Settings",
            (),
            {
                "language_mode": "auto",
                "language_favorites": ["en", "es", None],
                "audio_input_device": None,
            },
        )()
        self.microphone_test_started = False
        self.notifications: list[tuple[str, str]] = []

    def open_hotkey_settings(self) -> None:
        self.hotkey_settings_opened = True

    def open_language_settings(self) -> None:
        self.language_settings_opened = True

    def set_language_mode(self, mode: str) -> None:
        self.settings.language_mode = mode

    def set_audio_input_device(self, device: int | None) -> None:
        self.settings.audio_input_device = device

    def start_microphone_test(self) -> None:
        self.microphone_test_started = True

    def notify(self, title: str, message: str) -> None:
        self.notifications.append((title, message))


class FakeIcon:
    def __init__(self) -> None:
        self.stopped = False
        self.title_updates: list[str] = []
        self.icon_updates = 0
        self.notifications: list[tuple[str, str]] = []

    @property
    def title(self) -> str:
        return self.title_updates[-1] if self.title_updates else ""

    @title.setter
    def title(self, value: str) -> None:
        self.title_updates.append(value)

    @property
    def icon(self):
        return None

    @icon.setter
    def icon(self, value) -> None:
        self.icon_updates += 1

    def stop(self) -> None:
        self.stopped = True

    def notify(self, message: str, title: str) -> None:
        self.notifications.append((title, message))

    def update_menu(self) -> None:
        return None


def test_stop_detaches_icon_before_later_worker_updates():
    tray = TrayApp(controller=None)
    icon = FakeIcon()
    tray._icon = icon

    tray.stop()
    tray.set_status("Recording")
    tray.notify("Speech", "Still running")

    assert icon.stopped is True
    assert icon.title_updates == []
    assert icon.icon_updates == 0
    assert icon.notifications == []


def test_tray_opens_in_app_hotkey_settings():
    controller = FakeController()
    tray = TrayApp(controller)

    menu = tray._make_menu(FakeMenu, FakeMenuItem)
    settings_item = next(
        item for item in menu.items if item.label == "Hotkey Settings..."
    )
    settings_item.action(None, None)

    assert controller.hotkey_settings_opened is True


def test_tray_shows_update_check_only_on_windows(monkeypatch):
    controller = FakeController()
    tray = TrayApp(controller)

    monkeypatch.setattr(tray_module.sys, "platform", "win32")
    windows_menu = tray._make_menu(FakeMenu, FakeMenuItem)
    windows_update = next(
        item for item in windows_menu.items if item.label == "Check for Updates"
    )

    monkeypatch.setattr(tray_module.sys, "platform", "linux")
    linux_menu = tray._make_menu(FakeMenu, FakeMenuItem)
    linux_update = next(
        item for item in linux_menu.items if item.label == "Check for Updates"
    )

    assert windows_update.options["visible"] is True
    assert linux_update.options["visible"] is False


def test_linux_tray_rejects_backend_without_menus(monkeypatch):
    class MenuLessIcon:
        HAS_MENU = False

    pystray = types.ModuleType("pystray")
    pystray.Icon = MenuLessIcon
    pystray.Menu = FakeMenu
    pystray.MenuItem = FakeMenuItem
    monkeypatch.setitem(sys.modules, "pystray", pystray)
    monkeypatch.setattr(tray_module.sys, "platform", "linux")

    with pytest.raises(RuntimeError, match="does not support menus"):
        TrayApp(FakeController()).run()


def test_tray_exposes_featured_and_searchable_language_settings():
    controller = FakeController()
    tray = TrayApp(controller)

    menu = tray._make_menu(FakeMenu, FakeMenuItem)
    language_item = next(item for item in menu.items if item.label == "Language")
    labels = [item.label for item in language_item.action.items]
    french_item = next(item for item in language_item.action.items if item.label == "French")
    settings_item = next(
        item for item in language_item.action.items if item.label == "Language Settings..."
    )
    french_item.action(None, None)
    settings_item.action(None, None)

    assert "Auto" in labels
    assert "English" in labels
    assert "Portuguese" in labels
    assert controller.settings.language_mode == "fr"
    assert controller.language_settings_opened is True


def test_tray_places_language_favorites_before_the_featured_languages():
    controller = FakeController()
    controller.settings.language_favorites = ["fr", "ja", None]
    tray = TrayApp(controller)

    menu = tray._make_menu(FakeMenu, FakeMenuItem)
    language_item = next(item for item in menu.items if item.label == "Language")
    labels = [item.label for item in language_item.action.items]

    assert labels[:3] == ["Auto", "French", "Japanese"]


def test_tray_exposes_microphone_selection_and_test(monkeypatch):
    monkeypatch.setattr(
        tray_module,
        "list_audio_input_devices",
        lambda: (
            AudioInputDevice(index=2, name="Built-in Mic", input_channels=2),
            AudioInputDevice(index=5, name="USB Mic", input_channels=1),
        ),
    )
    controller = FakeController()
    tray = TrayApp(controller)

    menu = tray._make_menu(FakeMenu, FakeMenuItem)
    microphone_item = next(item for item in menu.items if item.label == "Microphone")
    labels = [item.label for item in microphone_item.action.items]
    usb_item = next(
        item for item in microphone_item.action.items if item.label == "USB Mic [5]"
    )
    test_item = next(
        item for item in microphone_item.action.items if item.label == "Test Microphone"
    )

    usb_item.action(None, None)
    test_item.action(None, None)

    assert labels == [
        "System Default",
        "Built-in Mic [2]",
        "USB Mic [5]",
        "Test Microphone",
    ]
    assert controller.settings.audio_input_device == 5
    assert controller.microphone_test_started is True


def test_tray_shows_unavailable_saved_microphone(monkeypatch):
    monkeypatch.setattr(tray_module, "list_audio_input_devices", lambda: ())
    controller = FakeController()
    controller.settings.audio_input_device = 9
    tray = TrayApp(controller)

    menu = tray._make_menu(FakeMenu, FakeMenuItem)
    microphone_item = next(item for item in menu.items if item.label == "Microphone")
    unavailable = next(
        item
        for item in microphone_item.action.items
        if item.label == "Unavailable microphone [9]"
    )

    assert unavailable.options["enabled"] is False
