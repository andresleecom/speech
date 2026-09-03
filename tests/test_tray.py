import logging
import sys
import types

import pytest

import winwhisper.audio_inputs as audio_inputs
import winwhisper.startup as startup_module
import winwhisper.tray as tray_module
from winwhisper.audio_inputs import AudioInputDevice
from winwhisper.branding import APP_NAME
from winwhisper.hotkey_settings import display_hotkey
from winwhisper.tray import TrayApp


class FakeMenu:
    def __init__(self, *items) -> None:
        self._items = items

    @property
    def items(self):
        if len(self._items) == 1 and callable(self._items[0]):
            return tuple(self._items[0]())
        return self._items


class FakeMenuItem:
    def __init__(self, label, action, **kwargs) -> None:
        self.label = label
        self.action = action
        self.options = kwargs


class FakeController:
    def __init__(self) -> None:
        self.hotkey_settings_opened = False
        self.language_settings_opened = False
        self.permissions_opened = False
        self.log_folder_opened = False
        self.settings = type(
            "Settings",
            (),
            {
                "language_mode": "auto",
                "language_favorites": ["en", "es", None],
                "audio_input_device": None,
                "audio_input_device_name": None,
                "audio_input_device_host_api": None,
                "hotkeys": {"toggle_recording": "<ctrl>+<alt>+<space>"},
            },
        )()
        self.microphone_test_started = False
        self.notifications: list[tuple[str, str]] = []
        self.microphone_label = None

    def open_hotkey_settings(self) -> None:
        self.hotkey_settings_opened = True

    def open_language_settings(self) -> None:
        self.language_settings_opened = True

    def open_permission_setup(self) -> None:
        self.permissions_opened = True

    def open_log_folder(self) -> None:
        self.log_folder_opened = True

    def set_language_mode(self, mode: str) -> None:
        self.settings.language_mode = mode

    def set_audio_input_device(self, device: int | None) -> None:
        if device is None:
            self.set_audio_input_selection(None, None)
            return
        for candidate in getattr(self, "_devices", ()):
            if candidate.index == device:
                self.set_audio_input_selection(candidate.name, candidate.host_api)
                return

    def set_audio_input_selection(
        self, name: str | None, host_api: str | None
    ) -> None:
        self.settings.audio_input_device_name = name
        self.settings.audio_input_device_host_api = host_api
        self.settings.audio_input_device = next(
            (
                candidate.index
                for candidate in getattr(self, "_devices", ())
                if candidate.name == name and candidate.host_api == (host_api or "")
            ),
            None,
        )

    def start_microphone_test(self) -> None:
        self.microphone_test_started = True

    def notify(self, title: str, message: str) -> None:
        self.notifications.append((title, message))


class FakeIcon:
    def __init__(self) -> None:
        self.stopped = False
        self.title_updates: list[str] = []
        self.icon_updates = 0
        self.menu_updates = 0
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
        self.menu_updates += 1


class FakeTimer:
    created = []

    def __init__(self, interval, callback) -> None:
        self.interval = interval
        self.callback = callback
        self.daemon = False
        self.started = False
        self.cancelled = False
        self.created.append(self)

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        assert self.started is True
        assert self.cancelled is False
        self.callback()


@pytest.fixture(autouse=True)
def avoid_live_audio_device_access(monkeypatch):
    monkeypatch.setattr(tray_module, "refresh_audio_device_table", lambda: None)
    monkeypatch.setattr(tray_module, "input_device_signature", lambda: None)
    monkeypatch.setattr(audio_inputs, "_device_supports_capture", lambda row: True)

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


def test_tray_delivers_notifications_queued_before_run(monkeypatch):
    created = []

    class FakeRunnableIcon:
        HAS_MENU = True

        def __init__(self, name, image, title, menu) -> None:
            self.visible = False
            self.notifications: list[tuple[str, str]] = []
            created.append(self)

        def run(self, setup=None) -> None:
            if setup is not None:
                setup(self)

        def notify(self, message: str, title: str) -> None:
            self.notifications.append((title, message))

        def update_menu(self) -> None:
            return None

        def stop(self) -> None:
            return None

    pystray = types.ModuleType("pystray")
    pystray.Icon = FakeRunnableIcon
    pystray.Menu = FakeMenu
    pystray.MenuItem = FakeMenuItem
    monkeypatch.setitem(sys.modules, "pystray", pystray)

    tray = TrayApp(FakeController())
    tray._make_icon_image = lambda: "fake-image"
    tray.notify("Speech", "First")
    tray.notify("Speech", "Second")
    tray.run()

    assert len(created) == 1
    assert created[0].visible is True
    assert created[0].notifications == [("Speech", "First"), ("Speech", "Second")]


def test_tray_refreshes_menu_only_when_input_signature_changes(monkeypatch, caplog):
    signatures = iter(
        [
            ("Built-in Mic",),
            ("Built-in Mic",),
            ("Built-in Mic", "USB Mic"),
        ]
    )
    refreshes: list[str] = []
    FakeTimer.created.clear()
    monkeypatch.setattr(tray_module, "input_device_signature", lambda: next(signatures))
    monkeypatch.setattr(
        tray_module,
        "refresh_audio_device_table",
        lambda: refreshes.append("refresh"),
    )
    monkeypatch.setattr(tray_module.threading, "Timer", FakeTimer)
    tray = TrayApp(FakeController())
    icon = FakeIcon()
    tray._icon = icon

    with caplog.at_level(logging.INFO, logger="winwhisper.tray"):
        tray._on_icon_ready(icon)
        first_timer = FakeTimer.created[0]
        first_timer.fire()
        assert icon.menu_updates == 0
        assert refreshes == []

        second_timer = FakeTimer.created[1]
        second_timer.fire()

    assert icon.menu_updates == 1
    assert refreshes == ["refresh"]
    assert len(FakeTimer.created) == 3
    assert all(timer.interval == 2.0 for timer in FakeTimer.created)
    assert all(timer.daemon is True for timer in FakeTimer.created)
    assert "Input devices changed; microphone menu refreshed." in caplog.messages
    tray.stop()


def test_tray_stops_input_device_polling(monkeypatch):
    FakeTimer.created.clear()
    monkeypatch.setattr(
        tray_module,
        "input_device_signature",
        lambda: ("Built-in Mic",),
    )
    monkeypatch.setattr(tray_module.threading, "Timer", FakeTimer)
    tray = TrayApp(FakeController())
    icon = FakeIcon()
    tray._icon = icon

    tray._on_icon_ready(icon)
    timer = FakeTimer.created[0]
    tray.stop()
    timer.callback()

    assert timer.cancelled is True
    assert len(FakeTimer.created) == 1
    assert icon.menu_updates == 0
    assert icon.stopped is True


def test_tray_menu_shows_version_and_opens_log_folder():
    from winwhisper import __version__

    controller = FakeController()
    tray = TrayApp(controller)

    menu = tray._make_menu(FakeMenu, FakeMenuItem)
    version_item = menu.items[0]
    log_item = next(item for item in menu.items if item.label == "Open Log Folder")
    log_item.action(None, None)

    assert version_item.label == f"Speech {__version__}"
    assert version_item.options.get("enabled") is False
    assert controller.log_folder_opened is True


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
    monkeypatch.setattr(tray_module, "list_audio_input_devices", lambda: ())

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


def test_tray_shows_permissions_only_on_macos_and_opens_assistant(monkeypatch):
    controller = FakeController()
    tray = TrayApp(controller)

    monkeypatch.setattr(tray_module.sys, "platform", "darwin")
    macos_menu = tray._make_menu(FakeMenu, FakeMenuItem)
    permissions_item = next(
        item for item in macos_menu.items if item.label == "Permissions..."
    )
    permissions_item.action(None, None)

    monkeypatch.setattr(tray_module.sys, "platform", "linux")
    linux_menu = tray._make_menu(FakeMenu, FakeMenuItem)
    linux_permissions = next(
        item for item in linux_menu.items if item.label == "Permissions..."
    )

    assert permissions_item.options["visible"] is True
    assert linux_permissions.options["visible"] is False
    assert controller.permissions_opened is True


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
    devices = (
        AudioInputDevice(
            index=2, name="Built-in Mic", input_channels=2, host_api="MME"
        ),
        AudioInputDevice(
            index=5, name="USB Mic", input_channels=1, host_api="MME"
        ),
    )
    monkeypatch.setattr(tray_module, "list_audio_input_devices", lambda: devices)
    controller = FakeController()
    controller._devices = devices
    tray = TrayApp(controller)

    menu = tray._make_menu(FakeMenu, FakeMenuItem)
    microphone_item = next(item for item in menu.items if item.label == "Microphone")
    labels = [item.label for item in microphone_item.action.items]
    usb_item = next(
        item for item in microphone_item.action.items if item.label == "USB Mic"
    )
    test_item = next(
        item for item in microphone_item.action.items if item.label == "Test Microphone"
    )

    usb_item.action(None, None)
    test_item.action(None, None)

    assert labels == [
        "System Default",
        "Built-in Mic",
        "USB Mic",
        "Test Microphone",
    ]
    assert controller.settings.audio_input_device == 5
    assert controller.settings.audio_input_device_name == "USB Mic"
    assert controller.settings.audio_input_device_host_api == "MME"
    assert controller.microphone_test_started is True


def test_tray_checks_microphone_by_identity_when_hint_is_stale(monkeypatch):
    devices = (
        AudioInputDevice(
            index=2, name="PodMic", input_channels=1, host_api="MME"
        ),
    )
    monkeypatch.setattr(tray_module, "list_audio_input_devices", lambda: devices)
    controller = FakeController()
    controller.settings.audio_input_device = 3
    controller.settings.audio_input_device_name = "PodMic"
    controller.settings.audio_input_device_host_api = "MME"
    tray = TrayApp(controller)

    menu = tray._make_menu(FakeMenu, FakeMenuItem)
    microphone_item = next(item for item in menu.items if item.label == "Microphone")
    podmic = next(
        item for item in microphone_item.action.items if item.label == "PodMic"
    )
    assert podmic.options["checked"](None) is True


def test_tray_microphone_menu_lists_devices_without_refreshing(monkeypatch):
    devices = [
        AudioInputDevice(
            index=2, name="Built-in Mic", input_channels=2, host_api="MME"
        )
    ]
    refreshes: list[str] = []
    monkeypatch.setattr(tray_module, "list_audio_input_devices", lambda: tuple(devices))
    monkeypatch.setattr(
        tray_module,
        "refresh_audio_device_table",
        lambda: refreshes.append("refresh"),
    )
    tray = TrayApp(FakeController())

    menu = tray._make_menu(FakeMenu, FakeMenuItem)
    microphone_item = next(item for item in menu.items if item.label == "Microphone")
    first_labels = [item.label for item in microphone_item.action.items]
    devices.append(
        AudioInputDevice(
            index=8, name="Headset Mic", input_channels=1, host_api="MME"
        )
    )
    second_labels = [item.label for item in microphone_item.action.items]

    assert "Headset Mic" not in first_labels
    assert "Headset Mic" in second_labels
    assert refreshes == []


def test_tray_checks_saved_name_when_host_api_row_is_missing(monkeypatch):
    devices = (
        AudioInputDevice(
            index=22,
            name="PodMic",
            input_channels=1,
            host_api="Windows WASAPI",
        ),
    )
    monkeypatch.setattr(tray_module, "list_audio_input_devices", lambda: devices)
    controller = FakeController()
    controller.settings.audio_input_device_name = "PodMic"
    controller.settings.audio_input_device_host_api = "MME"
    tray = TrayApp(controller)

    menu = tray._make_menu(FakeMenu, FakeMenuItem)
    microphone_item = next(item for item in menu.items if item.label == "Microphone")
    podmic = next(
        item for item in microphone_item.action.items if item.label == "PodMic"
    )

    assert podmic.options["checked"](None) is True


def test_tray_set_microphone_label_updates_tooltip():
    tray = TrayApp(FakeController())
    icon = FakeIcon()
    tray._icon = icon
    tray.set_status("Idle")
    tray.set_microphone_label("PodMic [2]")

    expected_hotkey = display_hotkey("<ctrl>+<alt>+<space>")
    assert icon.title_updates[-1] == f"Speech - Idle - PodMic [2] - {expected_hotkey}"


def test_tray_toggle_label_includes_display_hotkey(monkeypatch):
    monkeypatch.setattr(tray_module.sys, "platform", "win32")
    controller = FakeController()
    tray = TrayApp(controller)

    menu = tray._make_menu(FakeMenu, FakeMenuItem)
    toggle = menu.items[1]
    label = toggle.label(None) if callable(toggle.label) else toggle.label

    assert label == "Start/Stop Recording (Ctrl + Alt + Space)"


def test_tray_start_at_login_only_on_windows(monkeypatch):
    controller = FakeController()
    tray = TrayApp(controller)

    monkeypatch.setattr(tray_module.sys, "platform", "win32")
    windows_menu = tray._make_menu(FakeMenu, FakeMenuItem)
    windows_item = next(
        item for item in windows_menu.items if item.label == "Start at login"
    )

    monkeypatch.setattr(tray_module.sys, "platform", "linux")
    linux_menu = tray._make_menu(FakeMenu, FakeMenuItem)
    linux_item = next(
        item for item in linux_menu.items if item.label == "Start at login"
    )

    assert windows_item.options["visible"] is True
    assert linux_item.options["visible"] is False


def test_tray_enable_startup_from_source_notifies_and_writes_nothing(monkeypatch):
    fake = types.SimpleNamespace(set_calls=[])

    def fake_enable(exe_path: str) -> bool:
        fake.set_calls.append(exe_path)
        return True

    monkeypatch.setattr(startup_module, "is_enabled", lambda: False)
    monkeypatch.setattr(startup_module, "installed_executable", lambda: None)
    monkeypatch.setattr(startup_module, "enable", fake_enable)

    controller = FakeController()
    tray = TrayApp(controller)
    tray._icon = FakeIcon()
    tray._on_toggle_startup(None, None)

    assert fake.set_calls == []
    assert controller.notifications == [
        (APP_NAME, "Start at login is available in the installed Speech app.")
    ]


def test_tray_enable_startup_from_frozen_writes_quoted_path(monkeypatch):
    class FakeWinreg:
        HKEY_CURRENT_USER = object()
        KEY_SET_VALUE = 2
        REG_SZ = 1

        def __init__(self) -> None:
            self.values: dict[str, str] = {}
            self.set_calls: list[tuple[str, str]] = []

        def OpenKey(self, hive, subkey, reserved=0, access=0):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def QueryValueEx(self, key, name):
            if name not in self.values:
                raise OSError(2, "not found")
            return self.values[name], self.REG_SZ

        def SetValueEx(self, key, name, reserved, value_type, value):
            self.values[name] = value
            self.set_calls.append((name, value))

    fake = FakeWinreg()
    module = types.ModuleType("winreg")
    module.HKEY_CURRENT_USER = fake.HKEY_CURRENT_USER
    module.KEY_SET_VALUE = fake.KEY_SET_VALUE
    module.REG_SZ = fake.REG_SZ
    module.OpenKey = fake.OpenKey
    module.QueryValueEx = fake.QueryValueEx
    module.SetValueEx = fake.SetValueEx
    monkeypatch.setitem(sys.modules, "winreg", module)
    monkeypatch.setattr(startup_module.sys, "platform", "win32")
    monkeypatch.setattr(startup_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        startup_module.sys, "executable", r"C:\Programs\Speech\Speech.exe"
    )

    controller = FakeController()
    tray = TrayApp(controller)
    tray._icon = FakeIcon()
    tray._on_toggle_startup(None, None)

    assert fake.set_calls == [("Speech", r'"C:\Programs\Speech\Speech.exe"')]
    assert controller.notifications == []


def test_tray_shows_unavailable_saved_microphone(monkeypatch):
    monkeypatch.setattr(tray_module, "list_audio_input_devices", lambda: ())
    controller = FakeController()
    controller.settings.audio_input_device = 9
    controller.settings.audio_input_device_name = "Missing Mic"
    controller.settings.audio_input_device_host_api = "MME"
    tray = TrayApp(controller)

    menu = tray._make_menu(FakeMenu, FakeMenuItem)
    microphone_item = next(item for item in menu.items if item.label == "Microphone")
    unavailable = next(
        item
        for item in microphone_item.action.items
        if item.label == "Missing Mic (unavailable)"
    )

    assert unavailable.options["enabled"] is False


def test_tray_icon_reuses_the_shared_app_mark():
    from winwhisper.branding import IDLE_ICON_COLOR, app_icon_image

    tray = TrayApp(FakeController())

    idle = tray._make_icon_image()
    assert idle.size == (64, 64)
    assert idle.tobytes() == app_icon_image(color=IDLE_ICON_COLOR).tobytes()

    tray._status = "Recording"
    recording = tray._make_icon_image()
    assert recording.tobytes() == (
        app_icon_image(color=tray_module._STATUS_COLORS["Recording"]).tobytes()
    )
    assert recording.tobytes() != idle.tobytes()
