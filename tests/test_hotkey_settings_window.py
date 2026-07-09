import sys
import types

import winwhisper.hotkey_settings_window as window_module
from winwhisper.hotkey_settings_window import HotkeySettingsWindow


class ImmediateThread:
    def __init__(self, target, args=(), **kwargs) -> None:
        self.target = target
        self.args = args

    def start(self) -> None:
        self.target(*self.args)


def test_windows_editor_uses_tk_adapter_without_blocking_caller(monkeypatch):
    calls = []
    hotkeys = {"toggle_recording": "<ctrl>+<alt>+<space>"}
    on_save = lambda values: None
    monkeypatch.setattr(window_module.sys, "platform", "win32")
    monkeypatch.setattr(window_module.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(
        window_module,
        "_run_tk_dialog",
        lambda values, callback, platform: calls.append(
            (values, callback, platform)
        ),
    )

    HotkeySettingsWindow().show(hotkeys, on_save)

    assert calls == [(hotkeys, on_save, "win32")]


def test_macos_editor_is_scheduled_on_appkit_main_queue(monkeypatch):
    calls = []
    hotkeys = {"toggle_recording": "<ctrl>+<alt>+<space>"}
    on_save = lambda values: None

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
        lambda values, callback: calls.append((values, callback)),
    )

    HotkeySettingsWindow().show(hotkeys, on_save)

    assert calls == [(hotkeys, on_save)]
