import sys
import types

import winwhisper.language_settings_window as window_module
from winwhisper.language_settings_window import (
    LanguageSettingsWindow,
    _filtered_choices,
)


class ImmediateThread:
    def __init__(self, target, args=(), **kwargs) -> None:
        self.target = target
        self.args = args

    def start(self) -> None:
        self.target(*self.args)


def test_favorite_picker_filter_keeps_matching_language_choices():
    assert _filtered_choices("", favorites=True)[:2] == (
        "Not pinned",
        "Afrikaans (af)",
    )
    assert _filtered_choices("French", favorites=True) == ("French (fr)",)
    assert _filtered_choices("not", favorites=True) == ("Not pinned",)


def test_windows_language_picker_uses_tk_adapter_without_blocking_caller(monkeypatch):
    calls = []
    favorites = ["en", "es", None]
    on_save = lambda mode, selected_favorites: None
    monkeypatch.setattr(window_module.sys, "platform", "win32")
    monkeypatch.setattr(window_module.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(
        window_module,
        "_run_tk_dialog",
        lambda mode, selected_favorites, callback: calls.append(
            (mode, selected_favorites, callback)
        ),
    )

    LanguageSettingsWindow().show("French (fr)", favorites, on_save)

    assert calls == [("fr", ("en", "es", None), on_save)]


def test_macos_language_picker_is_scheduled_on_appkit_main_queue(monkeypatch):
    calls = []
    favorites = ["en", "es", None]
    on_save = lambda mode, selected_favorites: None

    class FakeMainQueue:
        def addOperationWithBlock_(self, operation) -> None:
            operation()

    class FakeOperationQueue:
        @classmethod
        def mainQueue(cls):
            return FakeMainQueue()

    foundation = types.SimpleNamespace(NSOperationQueue=FakeOperationQueue)
    monkeypatch.setitem(sys.modules, "Foundation", foundation)
    monkeypatch.setattr(window_module.sys, "platform", "darwin")
    monkeypatch.setattr(
        window_module,
        "_run_macos_dialog",
        lambda mode, selected_favorites, callback: calls.append(
            (mode, selected_favorites, callback)
        ),
    )

    LanguageSettingsWindow().show("Japanese", favorites, on_save)

    assert calls == [("ja", ("en", "es", None), on_save)]
