from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Any, Callable

_AUDIO_INPUT_ENTITLEMENT = "com.apple.security.device.audio-input"


class PermissionState(str, Enum):
    GRANTED = "granted"
    NOT_DETERMINED = "not_determined"
    MISSING = "missing"
    DENIED = "denied"
    RESTRICTED = "restricted"
    MISCONFIGURED = "misconfigured"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PermissionStatus:
    state: PermissionState
    detail: str = ""

    @property
    def ready(self) -> bool:
        return self.state is PermissionState.GRANTED


@dataclass(frozen=True)
class MacOSPermissionSnapshot:
    microphone: PermissionStatus
    input_monitoring: PermissionStatus
    accessibility: PermissionStatus

    @property
    def ready(self) -> bool:
        return (
            self.microphone.ready
            and self.input_monitoring.ready
            and self.accessibility.ready
        )

    @property
    def microphone_ready(self) -> bool:
        return self.microphone.ready

    @property
    def hotkeys_ready(self) -> bool:
        return self.input_monitoring.ready and self.accessibility.ready


def _granted_snapshot() -> MacOSPermissionSnapshot:
    granted = PermissionStatus(PermissionState.GRANTED)
    return MacOSPermissionSnapshot(granted, granted, granted)


def _plist_bytes(output: bytes) -> bytes:
    """Extract a plist when codesign writes diagnostics before it."""
    for marker in (b"<?xml", b"<plist", b"bplist"):
        index = output.find(marker)
        if index >= 0:
            return output[index:]
    return b""


def inspect_audio_input_entitlement(
    executable: str,
    *,
    run_command: Callable[..., Any] | None = None,
) -> bool | None:
    """Return the signed entitlement value, or None when it cannot be inspected.

    A successful codesign inspection with no entitlement payload is a definitive
    False. codesign uses stderr for ordinary diagnostics, so only a nonzero exit
    or an unavailable tool is treated as unknown.
    """
    runner = run_command or subprocess.run
    try:
        codesign = runner(
            [
                "/usr/bin/codesign",
                "--display",
                "--entitlements",
                "-",
                "--xml",
                executable,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if codesign.returncode != 0:
        return None

    plist_data = _plist_bytes(bytes(codesign.stdout or b""))
    if not plist_data:
        plist_data = _plist_bytes(bytes(codesign.stderr or b""))
    if not plist_data:
        return False

    try:
        converted = runner(
            ["/usr/bin/plutil", "-convert", "json", "-o", "-", "-"],
            input=plist_data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if converted.returncode != 0:
        return None

    try:
        entitlements = json.loads(bytes(converted.stdout).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(entitlements, dict):
        return None
    return entitlements.get(_AUDIO_INPUT_ENTITLEMENT) is True


@lru_cache(maxsize=1)
def audio_input_entitlement() -> bool | None:
    """Inspect the current process once; development runs do not need signing."""
    if not getattr(sys, "frozen", False):
        return True
    return inspect_audio_input_entitlement(sys.executable)


def clear_entitlement_cache() -> None:
    audio_input_entitlement.cache_clear()


def check_microphone_permission() -> PermissionStatus:
    if sys.platform != "darwin":
        return PermissionStatus(PermissionState.GRANTED)

    entitlement = audio_input_entitlement()
    if entitlement is False:
        return PermissionStatus(
            PermissionState.MISCONFIGURED,
            "This build lacks the required audio-input entitlement.",
        )

    try:
        import AVFoundation

        status = AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(
            AVFoundation.AVMediaTypeAudio
        )
        if status == AVFoundation.AVAuthorizationStatusAuthorized:
            return PermissionStatus(PermissionState.GRANTED)
        if status == AVFoundation.AVAuthorizationStatusNotDetermined:
            return PermissionStatus(PermissionState.NOT_DETERMINED)
        if status == AVFoundation.AVAuthorizationStatusDenied:
            return PermissionStatus(PermissionState.DENIED)
        if status == AVFoundation.AVAuthorizationStatusRestricted:
            return PermissionStatus(PermissionState.RESTRICTED)
    except Exception as exc:
        return PermissionStatus(
            PermissionState.UNKNOWN,
            f"Microphone permission could not be checked ({exc.__class__.__name__}).",
        )
    return PermissionStatus(PermissionState.UNKNOWN)


def check_input_monitoring_permission() -> PermissionStatus:
    if sys.platform != "darwin":
        return PermissionStatus(PermissionState.GRANTED)
    try:
        from Quartz import CGPreflightListenEventAccess

        if CGPreflightListenEventAccess():
            return PermissionStatus(PermissionState.GRANTED)
        # Quartz does not expose denied versus first use without requesting.
        return PermissionStatus(PermissionState.MISSING)
    except Exception as exc:
        return PermissionStatus(
            PermissionState.UNKNOWN,
            f"Input Monitoring could not be checked ({exc.__class__.__name__}).",
        )


def check_accessibility_permission() -> PermissionStatus:
    if sys.platform != "darwin":
        return PermissionStatus(PermissionState.GRANTED)
    try:
        from ApplicationServices import AXIsProcessTrusted

        if AXIsProcessTrusted():
            return PermissionStatus(PermissionState.GRANTED)
        # Accessibility likewise does not expose denied versus first use here.
        return PermissionStatus(PermissionState.MISSING)
    except Exception as exc:
        return PermissionStatus(
            PermissionState.UNKNOWN,
            f"Accessibility could not be checked ({exc.__class__.__name__}).",
        )


def get_permission_snapshot() -> MacOSPermissionSnapshot:
    if sys.platform != "darwin":
        return _granted_snapshot()
    return MacOSPermissionSnapshot(
        microphone=check_microphone_permission(),
        input_monitoring=check_input_monitoring_permission(),
        accessibility=check_accessibility_permission(),
    )


def request_microphone_access(completion: Callable[[bool], None]) -> None:
    """Start AVFoundation's asynchronous request and return immediately."""
    if sys.platform != "darwin":
        completion(True)
        return
    try:
        import AVFoundation

        AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
            AVFoundation.AVMediaTypeAudio,
            lambda allowed: completion(bool(allowed)),
        )
    except Exception:
        completion(False)


def request_input_monitoring_access() -> bool:
    if sys.platform != "darwin":
        return True
    try:
        from Quartz import CGRequestListenEventAccess

        return bool(CGRequestListenEventAccess())
    except Exception:
        return False


def request_accessibility_access() -> bool:
    if sys.platform != "darwin":
        return True
    try:
        from ApplicationServices import (
            AXIsProcessTrusted,
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )

        AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
        return bool(AXIsProcessTrusted())
    except Exception:
        return False


_PRIVACY_PANES = {
    "microphone": "Privacy_Microphone",
    "input_monitoring": "Privacy_ListenEvent",
    "accessibility": "Privacy_Accessibility",
}


def open_privacy_settings(permission: str) -> bool:
    if sys.platform != "darwin":
        return False
    pane = _PRIVACY_PANES.get(permission)
    if pane is None:
        raise ValueError(f"Unknown macOS permission: {permission!r}")
    try:
        from AppKit import NSWorkspace
        from Foundation import NSURL

        url = NSURL.URLWithString_(
            f"x-apple.systempreferences:com.apple.preference.security?{pane}"
        )
        return bool(url is not None and NSWorkspace.sharedWorkspace().openURL_(url))
    except Exception:
        return False
