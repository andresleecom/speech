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
        self.settings = type("Settings", (), {"language_mode": "auto"})()

    def open_hotkey_settings(self) -> None:
        self.hotkey_settings_opened = True

    def open_language_settings(self) -> None:
        self.language_settings_opened = True

    def set_language_mode(self, mode: str) -> None:
        self.settings.language_mode = mode


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
