import sys
import types

import winwhisper.focus as focus_module
from winwhisper.focus import foreground_matches, restore_foreground_window


class FakeProperty:
    def __init__(self, value: int) -> None:
        self.value = [value]


class FakeRoot:
    def __init__(self, active_windows: list[int]) -> None:
        self._active_windows = iter(active_windows)
        self._last_active_window = active_windows[-1]
        self.events: list[tuple[object, int]] = []

    def get_full_property(self, atom, property_type):
        try:
            self._last_active_window = next(self._active_windows)
        except StopIteration:
            pass
        return FakeProperty(self._last_active_window)

    def send_event(self, event, event_mask: int) -> None:
        self.events.append((event, event_mask))


class FakeDisplay:
    def __init__(self, active_windows: list[int]) -> None:
        self.root = FakeRoot(active_windows)
        self.closed = False
        self.syncs = 0

    def screen(self):
        return types.SimpleNamespace(root=self.root)

    def intern_atom(self, name: str):
        return name

    def create_resource_object(self, resource_type: str, resource_id: int):
        return types.SimpleNamespace(id=resource_id)

    def flush(self) -> None:
        return None

    def sync(self) -> None:
        self.syncs += 1

    def close(self) -> None:
        self.closed = True


def install_fake_xlib(monkeypatch):
    xlib = types.ModuleType("Xlib")
    xlib.X = types.SimpleNamespace(
        AnyPropertyType=0,
        CurrentTime=0,
        SubstructureRedirectMask=1,
        SubstructureNotifyMask=2,
    )
    xlib.protocol = types.SimpleNamespace(
        event=types.SimpleNamespace(ClientMessage=lambda **kwargs: kwargs)
    )
    monkeypatch.setitem(sys.modules, "Xlib", xlib)


class FakeUser32:
    def __init__(
        self,
        foreground_windows: list[int],
        process_ids: dict[int, int],
    ) -> None:
        self._foreground_windows = iter(foreground_windows)
        self._last_foreground_window = foreground_windows[-1]
        self.process_ids = process_ids
        self.foreground_checks = 0

    def GetForegroundWindow(self) -> int:
        self.foreground_checks += 1
        try:
            self._last_foreground_window = next(self._foreground_windows)
        except StopIteration:
            pass
        return self._last_foreground_window

    def GetWindowThreadProcessId(self, hwnd: int, process_id) -> int:
        process_id._obj.value = self.process_ids.get(hwnd, 0)
        return 1


def test_foreground_matches_accepts_another_window_from_same_process(monkeypatch):
    user32 = FakeUser32([888, 999], {777: 42, 888: 7, 999: 42})
    sleeps: list[float] = []
    monkeypatch.setattr(focus_module.os, "name", "nt")
    monkeypatch.setattr(
        focus_module.ctypes,
        "windll",
        types.SimpleNamespace(user32=user32),
    )
    monkeypatch.setattr(focus_module.time, "sleep", sleeps.append)

    assert foreground_matches(777) is True
    assert user32.foreground_checks == 2
    assert sleeps == [0.03]


def test_foreground_matches_returns_false_after_300_ms(monkeypatch):
    user32 = FakeUser32([888], {777: 42, 888: 7})
    sleeps: list[float] = []
    monkeypatch.setattr(focus_module.os, "name", "nt")
    monkeypatch.setattr(
        focus_module.ctypes,
        "windll",
        types.SimpleNamespace(user32=user32),
    )
    monkeypatch.setattr(focus_module.time, "sleep", sleeps.append)

    assert foreground_matches(777) is False
    assert user32.foreground_checks == 11
    assert sleeps == [0.03] * 10


def test_x11_restore_reports_failure_when_window_manager_refuses(monkeypatch):
    display = FakeDisplay([55, 55, 55, 55, 55, 55, 55])
    install_fake_xlib(monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(focus_module, "_x11_display", lambda: display)
    monkeypatch.setattr(focus_module.time, "sleep", lambda _seconds: None)

    assert restore_foreground_window(777) is False
    assert display.closed is True
    event, event_mask = display.root.events[0]
    assert event["data"] == (32, [1, 0, 55, 0, 0])
    assert event_mask == 3


def test_x11_restore_succeeds_only_after_target_becomes_active(monkeypatch):
    display = FakeDisplay([55, 55, 777])
    install_fake_xlib(monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(focus_module, "_x11_display", lambda: display)
    monkeypatch.setattr(focus_module.time, "sleep", lambda _seconds: None)

    assert restore_foreground_window(777) is True
    assert display.syncs == 2
    assert display.closed is True
