import sys

import pytest

import winwhisper.permission_setup_window as window_module
from winwhisper.macos_permissions import (
    MacOSPermissionSnapshot,
    PermissionState,
    PermissionStatus,
)
from winwhisper.permission_setup_window import (
    MIN_TEXT_GAP,
    PermissionSetupWindow,
    header_frames,
    permission_row_frames,
)


class FakeLogger:
    def exception(self, message) -> None:
        return None


@pytest.fixture(autouse=True)
def isolate_logger(monkeypatch):
    monkeypatch.setattr(window_module, "get_logger", lambda name: FakeLogger())


def snapshot(
    microphone=PermissionState.GRANTED,
    input_monitoring=PermissionState.GRANTED,
    accessibility=PermissionState.GRANTED,
):
    return MacOSPermissionSnapshot(
        PermissionStatus(microphone),
        PermissionStatus(input_monitoring),
        PermissionStatus(accessibility),
    )


def test_window_is_scheduled_on_appkit_main_queue(monkeypatch):
    operations = []
    presented = []
    monkeypatch.setattr(window_module.sys, "platform", "darwin")
    monkeypatch.setattr(window_module, "_schedule_on_main", operations.append)
    window = PermissionSetupWindow()
    monkeypatch.setattr(window, "_present", lambda: presented.append(True))

    window.show()

    assert presented == []
    assert len(operations) == 1
    operations[0]()
    assert presented == [True]


def test_permission_delegate_is_cached_and_clears_owner_on_window_close(monkeypatch):
    class ObjectiveCMeta(type):
        delegate_definitions = 0

        def __new__(metaclass, name, bases, namespace):
            if name == "PermissionWindowDelegate":
                if metaclass.delegate_definitions:
                    raise RuntimeError("Objective-C class was redefined")
                metaclass.delegate_definitions += 1
            return super().__new__(metaclass, name, bases, namespace)

    class FakeNSObject(metaclass=ObjectiveCMeta):
        pass

    class FakeApplication:
        def activateIgnoringOtherApps_(self, active):
            assert active is True

    fake_application = FakeApplication()

    class FakeNSApplication:
        @staticmethod
        def sharedApplication():
            return fake_application

    class FakeAppKit:
        NSObject = FakeNSObject
        NSApplication = FakeNSApplication

    monkeypatch.setattr(window_module, "_permission_window_delegate_class", None)
    monkeypatch.setitem(sys.modules, "AppKit", FakeAppKit)

    delegate_class = window_module._get_permission_window_delegate_class(FakeAppKit)
    assert (
        window_module._get_permission_window_delegate_class(FakeAppKit)
        is delegate_class
    )
    assert ObjectiveCMeta.delegate_definitions == 1
    assert hasattr(delegate_class, "windowWillClose_")
    assert not hasattr(delegate_class, "windowDidClose_")

    owner = PermissionSetupWindow()
    other_owner = PermissionSetupWindow()
    delegate = delegate_class()
    other_delegate = delegate_class()
    delegate._owner = owner
    other_delegate._owner = other_owner
    owner._window = object()
    owner._delegate = delegate
    owner._row_views["microphone"] = (object(), object(), object())
    owner._done_button = object()
    other_owner._delegate = other_delegate

    delegate.windowWillClose_(None)

    assert owner._window is None
    assert owner._delegate is None
    assert owner._row_views == {}
    assert owner._done_button is None
    assert delegate._owner is None
    assert other_delegate._owner is other_owner
    assert other_owner._delegate is other_delegate

    builds = []

    class RebuiltWindow:
        def center(self):
            return None

        def makeKeyAndOrderFront_(self, sender):
            return None

    def build_window(AppKit):
        builds.append(AppKit)
        owner._window = RebuiltWindow()

    monkeypatch.setattr(owner, "_build_window", build_window)
    monkeypatch.setattr(owner, "_refresh", lambda: None)

    owner._present()

    assert builds == [FakeAppKit]


def test_permission_copy_frames_have_no_vertical_overlap():
    title, subtitle = header_frames()
    assert subtitle.top <= title.y - MIN_TEXT_GAP
    for index in range(3):
        frames = permission_row_frames(index)
        assert frames["detail"].top <= frames["status"].y - MIN_TEXT_GAP
        assert frames["status"].top <= frames["purpose"].y - MIN_TEXT_GAP
        assert frames["detail"].width <= 350


def test_fresh_input_monitoring_action_requests_then_opens_settings(monkeypatch):
    events = []
    monkeypatch.setattr(
        window_module,
        "get_permission_snapshot",
        lambda: snapshot(input_monitoring=PermissionState.MISSING),
    )
    monkeypatch.setattr(
        window_module,
        "request_input_monitoring_access",
        lambda: events.append("request") or False,
    )
    monkeypatch.setattr(
        window_module,
        "open_privacy_settings",
        lambda pane: events.append(("settings", pane)) or True,
    )

    PermissionSetupWindow()._handle_input_monitoring_action()

    assert events == ["request", ("settings", "input_monitoring")]


def test_fresh_accessibility_action_requests_then_opens_settings(monkeypatch):
    events = []
    monkeypatch.setattr(
        window_module,
        "get_permission_snapshot",
        lambda: snapshot(accessibility=PermissionState.MISSING),
    )
    monkeypatch.setattr(
        window_module,
        "request_accessibility_access",
        lambda: events.append("request") or False,
    )
    monkeypatch.setattr(
        window_module,
        "open_privacy_settings",
        lambda pane: events.append(("settings", pane)) or True,
    )

    PermissionSetupWindow()._handle_accessibility_action()

    assert events == ["request", ("settings", "accessibility")]


def test_microphone_allow_returns_before_callback_and_refreshes_on_main(monkeypatch):
    retained = []
    scheduled = []
    monkeypatch.setattr(
        window_module,
        "get_permission_snapshot",
        lambda: snapshot(microphone=PermissionState.NOT_DETERMINED),
    )
    monkeypatch.setattr(
        window_module,
        "request_microphone_access",
        lambda callback: retained.append(callback),
    )
    monkeypatch.setattr(window_module, "_schedule_on_main", scheduled.append)
    window = PermissionSetupWindow()

    window._handle_microphone_action()

    assert len(retained) == 1
    assert scheduled == []
    retained[0](True)
    assert scheduled == [window._refresh]


def test_denied_microphone_action_opens_settings_without_request(monkeypatch):
    events = []
    monkeypatch.setattr(
        window_module,
        "get_permission_snapshot",
        lambda: snapshot(microphone=PermissionState.DENIED),
    )
    monkeypatch.setattr(
        window_module,
        "request_microphone_access",
        lambda callback: events.append("request"),
    )
    monkeypatch.setattr(
        window_module,
        "open_privacy_settings",
        lambda pane: events.append(("settings", pane)) or True,
    )

    PermissionSetupWindow()._handle_microphone_action()

    assert events == [("settings", "microphone")]


def test_unknown_row_recheck_does_not_prompt(monkeypatch):
    events = []
    monkeypatch.setattr(
        window_module,
        "get_permission_snapshot",
        lambda: snapshot(
            input_monitoring=PermissionState.UNKNOWN,
            accessibility=PermissionState.UNKNOWN,
        ),
    )
    monkeypatch.setattr(
        window_module,
        "request_input_monitoring_access",
        lambda: events.append("input"),
    )
    monkeypatch.setattr(
        window_module,
        "request_accessibility_access",
        lambda: events.append("accessibility"),
    )
    window = PermissionSetupWindow()

    window._handle_input_monitoring_action()
    window._handle_accessibility_action()

    assert events == []
