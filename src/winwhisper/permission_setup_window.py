from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from typing import Any, Callable

from .logger import get_logger
from .macos_permissions import (
    MacOSPermissionSnapshot,
    PermissionState,
    PermissionStatus,
    get_permission_snapshot,
    open_privacy_settings,
    request_accessibility_access,
    request_input_monitoring_access,
    request_microphone_access,
)

WINDOW_WIDTH = 520
WINDOW_HEIGHT = 500
MIN_TEXT_GAP = 4

_permission_window_delegate_class: Any | None = None
_permission_window_delegate_class_lock = threading.Lock()


@dataclass(frozen=True)
class Frame:
    x: int
    y: int
    width: int
    height: int

    @property
    def top(self) -> int:
        return self.y + self.height


def header_frames() -> tuple[Frame, Frame]:
    return Frame(24, 456, 472, 28), Frame(24, 408, 472, 40)


def permission_row_frames(index: int) -> dict[str, Frame]:
    if index not in range(3):
        raise ValueError("Permission row index must be 0, 1, or 2.")
    origin = 310 - (index * 96)
    return {
        "purpose": Frame(24, origin + 66, 350, 18),
        "status": Frame(24, origin + 44, 350, 18),
        "detail": Frame(24, origin + 4, 350, 36),
        "action": Frame(390, origin + 39, 106, 30),
    }


def _schedule_on_main(operation: Callable[[], None]) -> None:
    from Foundation import NSOperationQueue

    NSOperationQueue.mainQueue().addOperationWithBlock_(operation)


def _get_permission_window_delegate_class(AppKit: Any) -> Any:
    global _permission_window_delegate_class

    with _permission_window_delegate_class_lock:
        if _permission_window_delegate_class is None:

            class PermissionWindowDelegate(AppKit.NSObject):
                def microphoneAction_(self, sender: Any) -> None:
                    self._owner._handle_microphone_action()

                def inputMonitoringAction_(self, sender: Any) -> None:
                    self._owner._handle_input_monitoring_action()

                def accessibilityAction_(self, sender: Any) -> None:
                    self._owner._handle_accessibility_action()

                def recheckAction_(self, sender: Any) -> None:
                    self._owner._refresh()

                def closeAction_(self, sender: Any) -> None:
                    self._owner._window.close()

                def windowWillClose_(self, notification: Any) -> None:
                    owner = self._owner
                    if owner is not None:
                        owner._window = None
                        owner._delegate = None
                        owner._row_views.clear()
                        owner._done_button = None
                    self._owner = None

            _permission_window_delegate_class = PermissionWindowDelegate

    return _permission_window_delegate_class


def _status_copy(kind: str, status: PermissionStatus) -> tuple[str, str, str | None]:
    labels = {
        PermissionState.GRANTED: "Status: Ready",
        PermissionState.NOT_DETERMINED: "Status: Permission needed",
        PermissionState.MISSING: "Status: Permission needed",
        PermissionState.DENIED: "Status: Not allowed",
        PermissionState.RESTRICTED: "Status: Restricted",
        PermissionState.MISCONFIGURED: "Status: Build problem",
        PermissionState.UNKNOWN: "Status: Unable to check",
    }
    if status.state is PermissionState.GRANTED:
        details = {
            "microphone": "Used only while recording dictation.",
            "input_monitoring": "Lets Speech receive your global shortcut.",
            "accessibility": "Lets Speech restore focus and paste text.",
        }
        return labels[status.state], details[kind], None
    if status.state is PermissionState.MISCONFIGURED:
        return (
            labels[status.state],
            "Install a correctly signed Speech build, then try again.",
            None,
        )
    if status.state is PermissionState.UNKNOWN:
        return (
            labels[status.state],
            status.detail or "Close and reopen Speech, then recheck.",
            "Recheck",
        )
    if kind == "microphone":
        if status.state is PermissionState.NOT_DETERMINED:
            return labels[status.state], "Allow Speech to record your voice.", "Allow"
        return (
            labels[status.state],
            "Enable Speech in Privacy & Security > Microphone.",
            "Open Settings",
        )
    details = {
        "input_monitoring": "Required to receive the dictation shortcut.",
        "accessibility": "Required to paste into your active app.",
    }
    # These checks cannot distinguish first use from denial. The action always
    # requests first and opens Settings only if permission remains unavailable.
    return labels[status.state], details[kind], "Allow / Settings"


class PermissionSetupWindow:
    """One retained, non-modal AppKit permission assistant."""

    def __init__(self) -> None:
        self._logger = get_logger(__name__)
        self._lock = threading.Lock()
        self._scheduled = False
        self._window: Any | None = None
        self._delegate: Any | None = None
        self._row_views: dict[str, tuple[Any, Any, Any]] = {}
        self._done_button: Any | None = None

    def show(self) -> None:
        if sys.platform != "darwin":
            return
        with self._lock:
            if self._scheduled:
                return
            self._scheduled = True

        def present() -> None:
            try:
                self._present()
            except Exception:
                self._logger.exception("macOS permission assistant failed.")
            finally:
                with self._lock:
                    self._scheduled = False

        try:
            _schedule_on_main(present)
        except Exception:
            self._logger.exception("Could not schedule the macOS permission assistant.")
            with self._lock:
                self._scheduled = False

    def _present(self) -> None:
        import AppKit

        application = AppKit.NSApplication.sharedApplication()
        if self._window is None:
            self._build_window(AppKit)
        self._refresh()
        application.activateIgnoringOtherApps_(True)
        self._window.center()
        self._window.makeKeyAndOrderFront_(None)

    def _build_window(self, AppKit: Any) -> None:
        style = (
            AppKit.NSWindowStyleMaskTitled
            | AppKit.NSWindowStyleMaskClosable
            | AppKit.NSWindowStyleMaskMiniaturizable
        )
        window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            AppKit.NSMakeRect(0, 0, WINDOW_WIDTH, WINDOW_HEIGHT),
            style,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        window.setTitle_("Set up Speech")
        window.setReleasedWhenClosed_(False)
        delegate_class = _get_permission_window_delegate_class(AppKit)
        delegate = delegate_class.alloc().init()
        delegate._owner = self
        window.setDelegate_(delegate)
        content = window.contentView()

        title_frame, subtitle_frame = header_frames()
        title = self._label(AppKit, "Set up Speech", title_frame, bold=True)
        subtitle = self._label(
            AppKit,
            "Speech needs macOS permission to record and use global shortcuts.",
            subtitle_frame,
            wrapped=True,
        )
        content.addSubview_(title)
        content.addSubview_(subtitle)

        purposes = (
            ("microphone", "Microphone", "microphoneAction:"),
            ("input_monitoring", "Input Monitoring", "inputMonitoringAction:"),
            ("accessibility", "Accessibility", "accessibilityAction:"),
        )
        for index, (kind, purpose, selector) in enumerate(purposes):
            frames = permission_row_frames(index)
            purpose_view = self._label(
                AppKit, purpose, frames["purpose"], bold=True
            )
            status_view = self._label(AppKit, "", frames["status"])
            detail_view = self._label(
                AppKit, "", frames["detail"], wrapped=True
            )
            action = AppKit.NSButton.alloc().initWithFrame_(
                self._rect(AppKit, frames["action"])
            )
            action.setTarget_(delegate)
            action.setAction_(selector)
            action.setBezelStyle_(AppKit.NSBezelStyleRounded)
            content.addSubview_(purpose_view)
            content.addSubview_(status_view)
            content.addSubview_(detail_view)
            content.addSubview_(action)
            self._row_views[kind] = (status_view, detail_view, action)

        hint = self._label(
            AppKit,
            "After enabling shortcut permissions, quit and reopen Speech.",
            Frame(24, 75, 472, 32),
            wrapped=True,
        )
        content.addSubview_(hint)

        recheck = AppKit.NSButton.alloc().initWithFrame_(
            AppKit.NSMakeRect(272, 24, 106, 32)
        )
        recheck.setTitle_("Recheck")
        recheck.setTarget_(delegate)
        recheck.setAction_("recheckAction:")
        recheck.setBezelStyle_(AppKit.NSBezelStyleRounded)
        content.addSubview_(recheck)

        done = AppKit.NSButton.alloc().initWithFrame_(
            AppKit.NSMakeRect(390, 24, 106, 32)
        )
        done.setTarget_(delegate)
        done.setAction_("closeAction:")
        done.setBezelStyle_(AppKit.NSBezelStyleRounded)
        content.addSubview_(done)

        self._window = window
        self._delegate = delegate
        self._done_button = done

    @staticmethod
    def _rect(AppKit: Any, frame: Frame) -> Any:
        return AppKit.NSMakeRect(frame.x, frame.y, frame.width, frame.height)

    def _label(
        self,
        AppKit: Any,
        text: str,
        frame: Frame,
        *,
        bold: bool = False,
        wrapped: bool = False,
    ) -> Any:
        label = AppKit.NSTextField.labelWithString_(text)
        label.setFrame_(self._rect(AppKit, frame))
        if bold:
            label.setFont_(AppKit.NSFont.boldSystemFontOfSize_(13))
        if wrapped:
            label.setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)
            label.setUsesSingleLineMode_(False)
            if hasattr(label, "setMaximumNumberOfLines_"):
                label.setMaximumNumberOfLines_(2)
        return label

    def _refresh(self) -> MacOSPermissionSnapshot:
        snapshot = get_permission_snapshot()
        for kind, status in (
            ("microphone", snapshot.microphone),
            ("input_monitoring", snapshot.input_monitoring),
            ("accessibility", snapshot.accessibility),
        ):
            views = self._row_views.get(kind)
            if views is None:
                continue
            status_view, detail_view, action = views
            status_text, detail_text, action_text = _status_copy(kind, status)
            status_view.setStringValue_(status_text)
            detail_view.setStringValue_(detail_text)
            action.setHidden_(action_text is None)
            if action_text is not None:
                action.setTitle_(action_text)
        if self._done_button is not None:
            self._done_button.setTitle_("Done" if snapshot.ready else "Close")
        return snapshot

    def _schedule_refresh(self) -> None:
        try:
            _schedule_on_main(self._refresh)
        except Exception:
            self._logger.exception("Could not refresh the permission assistant.")

    def _handle_microphone_action(self) -> None:
        status = get_permission_snapshot().microphone
        if status.state in {
            PermissionState.NOT_DETERMINED,
            PermissionState.MISSING,
        }:
            request_microphone_access(lambda allowed: self._schedule_refresh())
            return
        if status.state in {
            PermissionState.DENIED,
            PermissionState.RESTRICTED,
        }:
            open_privacy_settings("microphone")
        self._refresh()

    def _handle_input_monitoring_action(self) -> None:
        status = get_permission_snapshot().input_monitoring
        if status.state is PermissionState.UNKNOWN:
            self._refresh()
            return
        if not request_input_monitoring_access():
            open_privacy_settings("input_monitoring")
        self._refresh()

    def _handle_accessibility_action(self) -> None:
        status = get_permission_snapshot().accessibility
        if status.state is PermissionState.UNKNOWN:
            self._refresh()
            return
        if not request_accessibility_access():
            open_privacy_settings("accessibility")
        self._refresh()
