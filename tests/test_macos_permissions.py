import json
import subprocess
import sys
import types

import winwhisper.macos_permissions as permissions
from winwhisper.macos_permissions import PermissionState


class CommandResult:
    def __init__(self, returncode=0, stdout=b"", stderr=b"") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_signed_executable_with_no_entitlements_is_misconfigured(monkeypatch):
    calls = []

    def run_command(args, **kwargs):
        calls.append(args)
        return CommandResult(
            returncode=0,
            stdout=b"",
            stderr=b"Executable=/Applications/Speech.app/Contents/MacOS/Speech\n",
        )

    assert (
        permissions.inspect_audio_input_entitlement(
            "/Applications/Speech.app/Contents/MacOS/Speech",
            run_command=run_command,
        )
        is False
    )
    assert calls == [
        [
            "/usr/bin/codesign",
            "--display",
            "--entitlements",
            "-",
            "--xml",
            "/Applications/Speech.app/Contents/MacOS/Speech",
        ]
    ]

    monkeypatch.setattr(permissions.sys, "platform", "darwin")
    monkeypatch.setattr(permissions.sys, "frozen", True, raising=False)
    monkeypatch.setattr(permissions, "audio_input_entitlement", lambda: False)
    assert (
        permissions.check_microphone_permission().state
        is PermissionState.MISCONFIGURED
    )


def test_explicit_false_audio_entitlement_is_misconfigured():
    results = iter(
        [
            CommandResult(stdout=b"<?xml version='1.0'?><plist></plist>"),
            CommandResult(
                stdout=json.dumps(
                    {"com.apple.security.device.audio-input": False}
                ).encode()
            ),
        ]
    )

    assert (
        permissions.inspect_audio_input_entitlement(
            "/tmp/Speech",
            run_command=lambda args, **kwargs: next(results),
        )
        is False
    )


def test_codesign_failure_or_unavailable_is_unknown():
    assert (
        permissions.inspect_audio_input_entitlement(
            "/tmp/Speech",
            run_command=lambda args, **kwargs: CommandResult(returncode=1),
        )
        is None
    )

    def unavailable(args, **kwargs):
        raise FileNotFoundError(args[0])

    assert (
        permissions.inspect_audio_input_entitlement(
            "/tmp/Speech",
            run_command=unavailable,
        )
        is None
    )


def test_permission_checks_do_not_call_request_apis(monkeypatch):
    calls = []
    avfoundation = types.SimpleNamespace(
        AVMediaTypeAudio="audio",
        AVAuthorizationStatusAuthorized=3,
        AVAuthorizationStatusNotDetermined=0,
        AVAuthorizationStatusDenied=2,
        AVAuthorizationStatusRestricted=1,
        AVCaptureDevice=types.SimpleNamespace(
            authorizationStatusForMediaType_=lambda media: 0,
            requestAccessForMediaType_completionHandler_=lambda *args: calls.append(
                "microphone"
            ),
        ),
    )
    quartz = types.SimpleNamespace(
        CGPreflightListenEventAccess=lambda: False,
        CGRequestListenEventAccess=lambda: calls.append("input"),
    )
    application_services = types.SimpleNamespace(
        AXIsProcessTrusted=lambda: False,
        AXIsProcessTrustedWithOptions=lambda options: calls.append("accessibility"),
        kAXTrustedCheckOptionPrompt="prompt",
    )
    monkeypatch.setitem(sys.modules, "AVFoundation", avfoundation)
    monkeypatch.setitem(sys.modules, "Quartz", quartz)
    monkeypatch.setitem(sys.modules, "ApplicationServices", application_services)
    monkeypatch.setattr(permissions.sys, "platform", "darwin")
    monkeypatch.setattr(permissions, "audio_input_entitlement", lambda: True)

    snapshot = permissions.get_permission_snapshot()

    assert snapshot.microphone.state is PermissionState.NOT_DETERMINED
    assert snapshot.input_monitoring.state is PermissionState.MISSING
    assert snapshot.accessibility.state is PermissionState.MISSING
    assert calls == []


def test_fresh_shortcut_requests_use_native_request_apis(monkeypatch):
    calls = []
    quartz = types.SimpleNamespace(
        CGRequestListenEventAccess=lambda: calls.append("input") or False
    )
    application_services = types.SimpleNamespace(
        AXIsProcessTrusted=lambda: False,
        AXIsProcessTrustedWithOptions=lambda options: calls.append(
            ("accessibility", options)
        ),
        kAXTrustedCheckOptionPrompt="prompt",
    )
    monkeypatch.setitem(sys.modules, "Quartz", quartz)
    monkeypatch.setitem(sys.modules, "ApplicationServices", application_services)
    monkeypatch.setattr(permissions.sys, "platform", "darwin")

    assert permissions.request_input_monitoring_access() is False
    assert permissions.request_accessibility_access() is False
    assert calls == [
        "input",
        ("accessibility", {"prompt": True}),
    ]


def test_microphone_request_uses_avfoundation_completion_without_waiting(monkeypatch):
    retained = []
    completed = []
    avfoundation = types.SimpleNamespace(
        AVMediaTypeAudio="audio",
        AVCaptureDevice=types.SimpleNamespace(
            requestAccessForMediaType_completionHandler_=lambda media, callback: (
                retained.append(callback)
            )
        ),
    )
    monkeypatch.setitem(sys.modules, "AVFoundation", avfoundation)
    monkeypatch.setattr(permissions.sys, "platform", "darwin")

    permissions.request_microphone_access(completed.append)

    assert completed == []
    assert len(retained) == 1
    retained[0](True)
    assert completed == [True]


def test_non_macos_snapshot_is_ready(monkeypatch):
    monkeypatch.setattr(permissions.sys, "platform", "linux")
    snapshot = permissions.get_permission_snapshot()

    assert snapshot.ready is True
    assert snapshot.hotkeys_ready is True
    assert snapshot.microphone_ready is True


def test_runtime_entitlement_inspection_is_cached_per_process(monkeypatch):
    calls = []
    permissions.clear_entitlement_cache()
    monkeypatch.setattr(permissions.sys, "frozen", True, raising=False)
    monkeypatch.setattr(permissions.sys, "executable", "/tmp/Speech")
    monkeypatch.setattr(
        permissions,
        "inspect_audio_input_entitlement",
        lambda executable: calls.append(executable) or True,
    )

    assert permissions.audio_input_entitlement() is True
    assert permissions.audio_input_entitlement() is True
    assert calls == ["/tmp/Speech"]
    permissions.clear_entitlement_cache()
