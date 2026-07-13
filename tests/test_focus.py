import sys
import types

import winwhisper.focus as focus_module
from winwhisper.focus import restore_foreground_window


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
