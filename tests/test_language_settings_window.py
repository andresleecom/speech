import sys
import types

import winwhisper.language_settings_window as window_module
from winwhisper.language_settings_window import LanguageSettingsWindow


class ImmediateThread:
    def __init__(self, target, args=(), **kwargs) -> None:
        self.target = target
        self.args = args

    def start(self) -> None:
        self.target(*self.args)


def test_windows_language_picker_uses_tk_adapter_without_blocking_caller(monkeypatch):
    calls = []
    on_save = lambda value: None
    monkeypatch.setattr(window_module.sys, "platform", "win32")
    monkeypatch.setattr(window_module.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(
        window_module,
        "_run_tk_dialog",
        lambda mode, callback: calls.append((mode, callback)),
    )

    LanguageSettingsWindow().show("French (fr)", on_save)

    assert calls == [("fr", on_save)]


def test_macos_language_picker_is_scheduled_on_appkit_main_queue(monkeypatch):
    calls = []
    on_save = lambda value: None

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
        lambda mode, callback: calls.append((mode, callback)),
    )

    LanguageSettingsWindow().show("Japanese", on_save)

    assert calls == [("ja", on_save)]
