from __future__ import annotations

import argparse
import ctypes
import io
import logging
import os
import sys
import threading
import time
from contextlib import redirect_stdout
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Literal

from . import __version__
from .audio_inputs import (
    SYSTEM_DEFAULT_INPUT_LABEL,
    group_physical_input_devices,
    list_audio_input_devices,
    normalize_audio_input_device,
)
from .branding import APP_NAME
from .config import Settings, app_data_dir, load_settings_report, save_settings
from .diagnostics import run_diagnostics as run_diagnostics_report
from .focus import (
    ScreenPoint,
    foreground_matches,
    get_cursor_anchor,
    get_foreground_window,
    get_window_process_name,
    restore_foreground_window,
)
from .formatter import clean_text
from .hotkey_settings import (
    HotkeyConfigurationError,
    display_hotkey,
    normalize_hotkey_profile,
)
from .hotkey_settings_window import HotkeySettingsWindow
from .hotkey_actions import TOGGLE_ACTION, TOGGLE_RELEASE_ACTION
from .hotkeys import HotkeyManager, windows_modifier_state
from .inserter import (
    PasteShortcut,
    copy_text_to_clipboard,
    insert_text,
    resolve_paste_shortcut,
)
from .language_settings_window import LanguageSettingsWindow
from .languages import (
    LanguageMode,
    normalize_language_favorites,
    normalize_language_mode,
)
from .logger import get_logger
from .macos_permissions import PermissionState, get_permission_snapshot
from .overlay import RecordingOverlay
from .permission_setup_window import PermissionSetupWindow
if sys.platform == "darwin":
    from .recorder_mac import MicrophoneTest, Recorder
    from .wake_word_source_mac import MacAudioSource as WakeWordAudioSource
else:
    from .recorder import MicrophoneTest, Recorder
    from .wake_word_source import SounddeviceSource as WakeWordAudioSource
from .transcriber import (
    MODEL_DOWNLOAD_SIZES_MB,
    ModelDownloadError,
    Transcriber,
    is_model_cached,
)
from .tray import TrayApp
from .update_controller import UpdateCoordinator
from .wake_word import (
    StopWordMonitor,
    WakeWordListener,
    WhisperPhraseDetector,
    language_hints,
    trim_trailing_phrase,
)

Status = Literal[
    "Idle",
    "Recording",
    "Testing microphone",
    "Transcribing",
    "Pasting",
    "Error",
    "Downloading model...",
]

STATUS_IDLE: Status = "Idle"
STATUS_RECORDING: Status = "Recording"
STATUS_TESTING_MICROPHONE: Status = "Testing microphone"
STATUS_TRANSCRIBING: Status = "Transcribing"
STATUS_PASTING: Status = "Pasting"
STATUS_ERROR: Status = "Error"
STATUS_DOWNLOADING_MODEL: Status = "Downloading model..."

_SINGLE_INSTANCE_MUTEX_NAME = "Local\\SpeechSingleInstanceMutex"
_SINGLE_INSTANCE_LOCK_FILE_NAME = "single-instance.lock"
_mutex_handle: Any | None = None
_single_instance_lock_handle: Any | None = None
# Notify the user if transcription is still running after this many seconds.
SLOW_TRANSCRIPTION_NOTIFY_SECONDS = 8.0
MICROPHONE_STOP_TIMEOUT_SECONDS = 5.0
MICROPHONE_STOP_TIMEOUT_EXIT_CODE = 70
MICROPHONE_TEST_SECONDS = 5.0
MICROPHONE_TEST_SIGNAL_THRESHOLD = 0.01
# Capture the real Thread class so progress watchers keep working even when
# tests replace threading.Thread with a synchronous helper.
_RealThread = threading.Thread


def _hard_exit(exit_code: int) -> None:
    os._exit(exit_code)


def _adopt_audio_input_identity(settings: Settings, logger: logging.Logger) -> None:
    """Fill name/host_api from the live table when only an index hint is saved."""
    if settings.audio_input_device is None or settings.audio_input_device_name:
        return
    try:
        for device in list_audio_input_devices():
            if device.index != settings.audio_input_device:
                continue
            settings.audio_input_device_name = device.name
            settings.audio_input_device_host_api = device.host_api
            save_settings(settings)
            logger.info(
                "Adopted microphone identity name=%r host_api=%r for index %s.",
                device.name,
                device.host_api,
                device.index,
            )
            return
    except Exception:
        logger.exception("Could not adopt microphone identity from the live device table.")



class AppController:
    def __init__(
        self,
        settings: Settings,
        *,
        notices: list[str] | None = None,
        first_run: bool = False,
    ) -> None:
        self.settings = settings
        self.first_run = first_run
        self._settings_notices = list(notices or ())
        self.logger = get_logger(__name__)
        self._lock = threading.RLock()
        self._microphone_test: MicrophoneTest | None = None
        self._microphone_test_cancel: threading.Event | None = None
        self.recorder = Recorder(
            on_max_duration=self._on_max_recording_duration,
            audio_input_device=settings.audio_input_device,
        )
        set_selection = getattr(self.recorder, "set_audio_input_selection", None)
        if callable(set_selection):
            set_selection(
                settings.audio_input_device_name,
                settings.audio_input_device_host_api,
                settings.audio_input_device,
            )
        self._previous_mic_resolution_fallback = False
        self.transcriber = Transcriber(settings, self._on_device_fallback)
        self.tray = TrayApp(self)
        self._sync_microphone_label()
        self.recording_overlay = RecordingOverlay(
            self.stop_from_overlay,
            self._current_microphone_level,
        )
        self.hotkey_settings_window = HotkeySettingsWindow()
        self.language_settings_window = LanguageSettingsWindow()
        self.permission_setup_window = PermissionSetupWindow()
        self.hotkeys = HotkeyManager(settings.hotkeys, self.on_hotkey)
        self._status: Status = STATUS_IDLE
        self._processing = False
        self._shutdown = False
        self._microphone_stop_complete: threading.Event | None = None
        self._recording_language_mode: LanguageMode | None = None
        self._paste_target_window: int | None = None
        self._paste_target_process_name: str | None = None
        self._overlay_anchor: ScreenPoint | None = None
        self._wake_detector = WhisperPhraseDetector(
            device=str(settings.device),
            compute_type=str(settings.compute_type),
            languages=language_hints(
                str(settings.language_mode),
                settings.language_favorites,
            ),
            model_size=str(settings.wake_model_size),
        )
        self._wake_listener: WakeWordListener | None = None
        self._stop_monitor: StopWordMonitor | None = None
        self._recording_started_by_wake_word = False
        self._pending_trim_phrase: str | None = None
        self.update_coordinator = UpdateCoordinator(
            self.settings,
            self.notify,
            self.exit_app,
            self.logger,
        )

    def run(self) -> None:
        if self.first_run:
            size = str(self.settings.model_size)
            mb = MODEL_DOWNLOAD_SIZES_MB.get(size, MODEL_DOWNLOAD_SIZES_MB["small"])
            hotkey = display_hotkey(
                self.settings.hotkeys.get("toggle_recording")
            )
            self.notify(
                APP_NAME,
                f"Press {hotkey} to dictate. The speech model ({size}, {mb} MB) "
                "downloads once. Microphone > Test Microphone checks your mic.",
            )
        for notice in self._settings_notices:
            self.notify(APP_NAME, notice)
        self._settings_notices.clear()
        self.set_status(STATUS_IDLE)
        start_hotkeys = True
        if sys.platform == "darwin":
            permissions = get_permission_snapshot()
            if not permissions.ready:
                self.open_permission_setup()
            if not permissions.hotkeys_ready:
                start_hotkeys = False
                self.logger.warning(
                    "Global hotkeys were not started because macOS shortcut "
                    "permissions are not ready."
                )
                self.notify(
                    APP_NAME,
                    "Finish Input Monitoring and Accessibility setup, then "
                    "quit and reopen Speech to enable the dictation hotkey.",
                )

        if start_hotkeys:
            try:
                activation = self.hotkeys.start()
                if activation.successful:
                    self.logger.info("Hotkey listener started.")
                else:
                    failed = ", ".join(
                        display_hotkey(combo) for combo in activation.failed
                    )
                    self.logger.warning("Hotkeys could not be registered: %s.", failed)
                    self.notify(
                        APP_NAME,
                        f"{failed} could not be registered. Open Hotkey Settings "
                        "and choose another shortcut.",
                    )
            except Exception:
                self._handle_error("Hotkey listener failed to start.")
        if getattr(self.hotkeys, "accessibility_missing", False):
            self.notify(
                APP_NAME,
                "Enable Speech under Privacy & Security > Accessibility, "
                "then relaunch, to use the dictation hotkey.",
            )
        if getattr(self.hotkeys, "input_monitoring_missing", False):
            self.notify(
                APP_NAME,
                "Enable Speech under Privacy & Security > Input Monitoring, "
                "then relaunch, to use the dictation hotkey.",
            )

        self._start_model_warmup()
        self._start_wake_listener()

        if sys.platform == "win32":
            try:
                self.update_coordinator.maybe_check_for_updates()
            except Exception as exc:
                self.logger.warning(
                    "Automatic update check could not start with %s.",
                    exc.__class__.__name__,
                )
        else:
            # Installer-based in-app updates are Windows-only. Packaged macOS
            # and Linux builds update manually from GitHub Releases.
            self.logger.info("Automatic updates are Windows-only for now.")

        try:
            self.tray.run()
        finally:
            self.stop()

    def stop(self) -> None:
        with self._lock:
            already_shutdown = self._shutdown
            self._shutdown = True

        if already_shutdown:
            self.recording_overlay.stop()
            self.tray.stop()
            return

        try:
            self.hotkeys.stop()
        except Exception:
            self.logger.exception("Hotkey listener failed to stop cleanly.")

        self._stop_stop_monitor()
        self._stop_wake_listener()

        self._stop_microphone_test(notify=False)

        if self.recorder.is_recording():
            stop_complete = self._new_microphone_stop_completion()
            self._start_microphone_stop_watchdog(stop_complete)
            try:
                self.recording_overlay.hide()
                try:
                    audio_path = self.recorder.stop_recording()
                finally:
                    stop_complete.set()
                if audio_path is not None:
                    self._delete_audio(audio_path)
            except Exception:
                self.logger.exception("Active recording failed to stop during shutdown.")

        with self._lock:
            stop_complete = self._microphone_stop_complete
        if stop_complete is not None and not stop_complete.wait(
            MICROPHONE_STOP_TIMEOUT_SECONDS
        ):
            self._handle_microphone_stop_timeout()
            return

        self.recording_overlay.stop()
        self.tray.stop()
        self.logger.info("%s stopped.", APP_NAME)

    def exit_app(self) -> None:
        self.logger.info("Exit requested.")
        self.stop()

    def stop_from_overlay(self) -> None:
        if self._stop_microphone_test():
            return
        self._request_stop(hide_overlay_if_idle=True)

    def on_hotkey(self, action: str) -> None:
        with self._lock:
            recording = self.recorder.is_recording()
            processing = self._processing
        self.logger.info(
            "Hotkey dispatch action=%s recording=%s processing=%s.",
            action,
            recording,
            processing,
        )
        if action == TOGGLE_ACTION:
            self.toggle()
            return
        if action == TOGGLE_RELEASE_ACTION:
            if recording and not processing:
                self.logger.info("Stopping dictation action=push_to_talk_release.")
                self._request_stop()
            else:
                self.logger.info(
                    "Ignoring push_to_talk_release while recording=%s processing=%s.",
                    recording,
                    processing,
                )
            return
        if action == "force_en":
            self._toggle_favorite_language(0)
            return
        if action == "force_es":
            self._toggle_favorite_language(1)
            return
        if action == "force_language_3":
            self._toggle_favorite_language(2)
            return

        self.logger.warning("Unknown hotkey action %s.", action)

    def toggle(self, language_override: LanguageMode | None = None) -> None:
        beep: tuple[int, int] | None = None
        start_error: BaseException | str | None = None

        if self._stop_microphone_test():
            return

        with self._lock:
            if self._processing:
                self.logger.info("Ignoring toggle while dictation is being processed.")
                return

            if self.recorder.is_recording():
                beep = self._begin_stop_locked()
            else:
                microphone_error = self._microphone_readiness_error()
                if microphone_error is not None:
                    start_error = microphone_error
                else:
                    language_mode = language_override or self.settings.language_mode
                    self._paste_target_window = get_foreground_window()
                    self._paste_target_process_name = get_window_process_name(
                        self._paste_target_window
                    )
                    self._overlay_anchor = get_cursor_anchor(self._paste_target_window)
                    wake_listener = self._wake_listener
                    if wake_listener is not None:
                        try:
                            wake_listener.pause()
                        except Exception:
                            self.logger.exception(
                                "Wake-word listener failed to pause before recording."
                            )
                    try:
                        self.recorder.start_recording()
                    except Exception as exc:
                        self._paste_target_window = None
                        self._paste_target_process_name = None
                        self._overlay_anchor = None
                        start_error = exc
                    else:
                        self._recording_language_mode = language_mode
                        self.logger.info(
                            "Recording started (language_mode=%s; overlay_anchor=%s).",
                            language_mode,
                            self._overlay_anchor,
                        )
                        self.recording_overlay.show(self._overlay_anchor)
                        self.set_status(STATUS_RECORDING)
                        beep = (880, 120)
                        self._maybe_toast_microphone_fallback()

        if start_error is not None:
            if isinstance(start_error, BaseException):
                message = str(start_error) or "Recording failed to start."
                self.logger.error(
                    "%s %s",
                    message,
                    getattr(start_error, "details", ""),
                    exc_info=start_error,
                )
                self._beep(220, 350)
                self.set_status(STATUS_ERROR)
                self.notify(APP_NAME, message)
            else:
                self._handle_error(start_error)
            self._resume_wake_listener_if_enabled()
            return
        if beep is not None:
            self._beep(*beep)

    def set_language_mode(self, mode: str) -> None:
        normalized = normalize_language_mode(mode)
        if normalized is None:
            self.logger.warning("Ignoring unsupported language mode %s.", mode)
            return
        self.set_language_preferences(normalized, self.settings.language_favorites)

    def set_language_preferences(
        self,
        mode: str,
        language_favorites: object,
    ) -> None:
        normalized = normalize_language_mode(mode)
        if normalized is None:
            raise ValueError(f"Unsupported language mode: {mode!r}")
        normalized_favorites = list(normalize_language_favorites(language_favorites))

        previous_mode = self.settings.language_mode
        previous_favorites = list(self.settings.language_favorites)
        self.settings.language_mode = normalized
        self.settings.language_favorites = normalized_favorites
        try:
            save_settings(self.settings)
        except Exception:
            self.settings.language_mode = previous_mode
            self.settings.language_favorites = previous_favorites
            raise

        self.tray.refresh_menu()
        self.logger.info(
            "Language preferences set: language_mode=%s; favorites=%s.",
            normalized,
            normalized_favorites,
        )

    def set_cleanup_mode(self, mode: str) -> None:
        if mode not in {"none", "basic", "llm"}:
            self.logger.warning("Ignoring unsupported cleanup mode %s.", mode)
            return

        self.settings.cleanup_mode = mode  # type: ignore[assignment]
        save_settings(self.settings)
        self.logger.info("Cleanup mode set to %s.", mode)

    def set_wake_word_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self.settings.wake_word_enabled:
            return

        self.settings.wake_word_enabled = enabled
        save_settings(self.settings)
        if enabled:
            self._start_wake_listener()
        else:
            self._stop_wake_listener()
        self.tray.refresh_menu()
        self.logger.info("Wake word %s.", "enabled" if enabled else "disabled")

    def _start_wake_listener(self) -> None:
        if not self.settings.wake_word_enabled:
            return
        with self._lock:
            if self._shutdown or self._wake_listener is not None:
                return
        try:
            source = WakeWordAudioSource(
                audio_input_device=self.settings.audio_input_device
            )
            set_selection = getattr(source, "set_audio_input_selection", None)
            if callable(set_selection):
                set_selection(
                    self.settings.audio_input_device_name,
                    self.settings.audio_input_device_host_api,
                    self.settings.audio_input_device,
                )
            listener = WakeWordListener(
                source,
                self.settings.wake_phrases,
                self._on_wake_word,
                detector=self._wake_detector,
            )
            listener.start()
        except Exception:
            self.logger.exception("Wake-word listener failed to start.")
            self.notify(
                APP_NAME,
                "Wake word could not start. Check the microphone, then toggle "
                "the wake word off and on.",
            )
            return
        with self._lock:
            self._wake_listener = listener

    def _stop_wake_listener(self) -> None:
        with self._lock:
            listener = self._wake_listener
            self._wake_listener = None
        if listener is None:
            return
        try:
            listener.stop()
        except Exception:
            self.logger.exception("Wake-word listener failed to stop cleanly.")

    def _resume_wake_listener_if_enabled(self) -> None:
        with self._lock:
            listener = self._wake_listener
            enabled = self.settings.wake_word_enabled
            shutdown = self._shutdown
        if listener is None or not enabled or shutdown:
            return
        try:
            listener.resume()
        except Exception:
            self.logger.exception("Wake-word listener failed to resume.")

    def _on_wake_word(self) -> None:
        with self._lock:
            if self._shutdown or self._processing or self.recorder.is_recording():
                self.logger.info("Ignoring wake word; dictation already active.")
                return
            listener = self._wake_listener

        if listener is not None:
            try:
                listener.pause()
            except Exception:
                self.logger.exception("Wake-word listener failed to pause.")

        with self._lock:
            self._recording_started_by_wake_word = True
        # The macOS recorder only buffers live samples (for the stop-word
        # monitor) when asked before start_recording.
        self.recorder.set_recent_audio_capture(True)
        self.toggle()
        with self._lock:
            started = self.recorder.is_recording()

        if started:
            monitor = StopWordMonitor(
                self.recorder,
                self.settings.stop_phrase,
                self.settings.wake_silence_timeout_seconds,
                self._on_voice_stop,
                detector=self._wake_detector,
            )
            monitor.start()
            with self._lock:
                self._stop_monitor = monitor
            return

        # Recording never started (microphone error or a mic test was
        # running); hand the microphone back to the listener.
        with self._lock:
            self._recording_started_by_wake_word = False
        if listener is not None:
            try:
                listener.resume()
            except Exception:
                self.logger.exception("Wake-word listener failed to resume.")

    def _on_voice_stop(self, reason: str) -> None:
        if reason == "phrase":
            with self._lock:
                self._pending_trim_phrase = self.settings.stop_phrase
        self._request_stop()

    def _stop_stop_monitor(self) -> None:
        with self._lock:
            monitor = self._stop_monitor
            self._stop_monitor = None
        if monitor is None:
            return
        try:
            monitor.stop()
        except Exception:
            self.logger.exception("Stop-word monitor failed to stop cleanly.")

    def set_audio_input_device(self, value: object) -> None:
        selected_device = normalize_audio_input_device(value)
        if selected_device is None:
            self.set_audio_input_selection(None, None)
            return

        try:
            for device in list_audio_input_devices():
                if device.index == selected_device:
                    self.set_audio_input_selection(device.name, device.host_api)
                    return
        except Exception:
            self.logger.exception(
                "Could not resolve microphone identity for index %s.",
                selected_device,
            )
        self.set_audio_input_selection(None, None)

    def set_audio_input_selection(
        self, name: str | None, host_api: str | None
    ) -> None:
        selected_device: int | None = None
        microphone_label = SYSTEM_DEFAULT_INPUT_LABEL
        if name is not None:
            microphone_label = name
            try:
                devices = list_audio_input_devices()
                selected_row = next(
                    (
                        device
                        for device in devices
                        if device.name == name
                        and device.host_api == (host_api or "")
                    ),
                    None,
                )
                if selected_row is not None:
                    selected_device = selected_row.index
                    for group in group_physical_input_devices(devices):
                        if selected_row in group.rows:
                            microphone_label = group.label
                            break
            except Exception:
                self.logger.exception(
                    "Could not resolve microphone identity name=%r host_api=%r.",
                    name,
                    host_api,
                )

        with self._lock:
            if self._processing or self.recorder.is_recording() or self._microphone_test:
                raise RuntimeError("Stop microphone capture before changing the microphone.")

            previous_device = self.settings.audio_input_device
            previous_name = self.settings.audio_input_device_name
            previous_host_api = self.settings.audio_input_device_host_api
            wake_was_running = self._wake_listener is not None

            set_selection = getattr(self.recorder, "set_audio_input_selection", None)
            if callable(set_selection):
                set_selection(name, host_api, selected_device)
            else:
                self.recorder.set_audio_input_device(selected_device)
            self.settings.audio_input_device = selected_device
            self.settings.audio_input_device_name = name
            self.settings.audio_input_device_host_api = host_api
            try:
                save_settings(self.settings)
            except Exception:
                self.settings.audio_input_device = previous_device
                self.settings.audio_input_device_name = previous_name
                self.settings.audio_input_device_host_api = previous_host_api
                if callable(set_selection):
                    set_selection(previous_name, previous_host_api, previous_device)
                else:
                    self.recorder.set_audio_input_device(previous_device)
                raise

            if wake_was_running:
                self._stop_wake_listener()

        if wake_was_running and self.settings.wake_word_enabled:
            self._start_wake_listener()

        self.tray.set_microphone_label(microphone_label)
        self.tray.refresh_menu()
        self.logger.info(
            "Audio input selection set to %s (name=%r, host_api=%r).",
            selected_device,
            name,
            host_api,
        )

    def start_microphone_test(self) -> None:
        microphone_error = self._microphone_readiness_error()
        if microphone_error is not None:
            raise RuntimeError(microphone_error)
        with self._lock:
            if self._shutdown:
                raise RuntimeError("Speech is shutting down.")
            if self._processing or self.recorder.is_recording():
                raise RuntimeError("Stop dictation before testing the microphone.")
            if self._microphone_test is not None:
                raise RuntimeError("A microphone test is already running.")

            microphone_test = MicrophoneTest(self.settings.audio_input_device)
            set_selection = getattr(microphone_test, "set_audio_input_selection", None)
            if callable(set_selection):
                set_selection(
                    self.settings.audio_input_device_name,
                    self.settings.audio_input_device_host_api,
                    self.settings.audio_input_device,
                )
            microphone_test.start()
            cancel = threading.Event()
            self._microphone_test = microphone_test
            self._microphone_test_cancel = cancel
            overlay_anchor = get_cursor_anchor(get_foreground_window())

        self.recording_overlay.show(overlay_anchor)
        self.set_status(STATUS_TESTING_MICROPHONE)
        self.notify(APP_NAME, "Testing microphone. Speak now.")
        _RealThread(
            target=self._finish_microphone_test_after_delay,
            args=(microphone_test, cancel),
            name="winwhisper-microphone-test",
            daemon=True,
        ).start()

    def _finish_microphone_test_after_delay(
        self,
        microphone_test: MicrophoneTest,
        cancel: threading.Event,
    ) -> None:
        if cancel.wait(MICROPHONE_TEST_SECONDS):
            return
        self._stop_microphone_test(microphone_test, completed=True)

    def set_hotkeys(self, hotkeys: dict[str, str]) -> None:
        normalized = normalize_hotkey_profile(
            hotkeys,
            language_favorites=self.settings.language_favorites,
        )
        if sys.platform == "darwin":
            self._set_hotkeys_macos(normalized)
            return
        self._set_hotkeys_live_rebind(normalized)

    def _set_hotkeys_macos(self, normalized: dict[str, str]) -> None:
        """Persist hotkeys on macOS without restarting the pynput listener.

        Replacing HotkeyManager from the AppKit settings modal races Text Services
        Manager work on the pynput worker thread and can crash Speech. Validate and
        save here; packaged builds relaunch after the modal unwinds.
        """
        previous_settings = dict(self.settings.hotkeys)
        self.settings.hotkeys = normalized
        try:
            save_settings(self.settings)
        except Exception as exc:
            self.settings.hotkeys = previous_settings
            raise HotkeyConfigurationError(
                "The hotkey settings could not be saved."
            ) from exc

        self.tray.refresh_menu()
        self.set_status(self._status)

        if self._try_schedule_macos_hotkey_relaunch():
            self.logger.info(
                "Hotkey settings saved; restarting %s to apply them.",
                APP_NAME,
            )
            self.notify(
                APP_NAME,
                "Hotkeys saved. Speech is restarting to apply them.",
            )
            return

        self.logger.info(
            "Hotkey settings saved; quit and reopen %s to apply them.",
            APP_NAME,
        )
        self.notify(
            APP_NAME,
            "Hotkeys saved. Quit and reopen Speech to apply them.",
        )

    def _try_schedule_macos_hotkey_relaunch(self) -> bool:
        """Launch a detached relaunch helper and queue exit after the modal returns.

        Returns True only when both the helper started and shutdown was queued.
        """
        if not getattr(sys, "frozen", False):
            return False
        app_path = _macos_app_bundle_path(sys.executable)
        if app_path is None:
            self.logger.warning(
                "Hotkey settings saved, but the Speech.app bundle path could not "
                "be resolved from %s.",
                sys.executable,
            )
            return False
        try:
            _launch_macos_relaunch_helper(pid=os.getpid(), app_path=app_path)
        except Exception:
            self.logger.exception("Could not launch the Speech relaunch helper.")
            return False
        try:
            _queue_macos_main_operation(self.exit_app)
        except Exception:
            self.logger.exception(
                "Could not schedule Speech shutdown after hotkey save."
            )
            return False
        return True

    def _set_hotkeys_live_rebind(self, normalized: dict[str, str]) -> None:
        """Replace the running hotkey manager (Windows/Linux)."""
        replacement = HotkeyManager(normalized, self.on_hotkey)
        previous = self.hotkeys
        previous_settings = dict(self.settings.hotkeys)
        previous.stop()
        try:
            activation = replacement.start()
            if not activation.successful:
                failed = ", ".join(display_hotkey(combo) for combo in activation.failed)
                raise HotkeyConfigurationError(
                    f"{failed} could not be registered; another application may "
                    "already be using it."
                )
            self.settings.hotkeys = normalized
            try:
                save_settings(self.settings)
            except Exception as exc:
                self.settings.hotkeys = previous_settings
                raise HotkeyConfigurationError(
                    "The hotkey settings could not be saved."
                ) from exc
        except Exception as update_error:
            replacement.stop()
            try:
                rollback = previous.start()
            except Exception as rollback_error:
                self.logger.exception("Previous hotkeys could not be restored.")
                raise HotkeyConfigurationError(
                    "The previous hotkeys could not be restored. Restart Speech "
                    "and choose a different shortcut."
                ) from rollback_error
            if not rollback.successful:
                failed = ", ".join(
                    display_hotkey(combo) for combo in rollback.failed
                )
                self.logger.error(
                    "Previous hotkeys could not be restored: %s.",
                    failed,
                )
                raise HotkeyConfigurationError(
                    f"The previous hotkeys could not be restored ({failed}). "
                    "Restart Speech and choose a different shortcut."
                ) from update_error
            raise
        self.hotkeys = replacement
        self.tray.refresh_menu()
        self.set_status(self._status)
        self.logger.info("Hotkey settings updated and applied without restart.")

    def open_hotkey_settings(self) -> None:
        def on_capture_begin() -> None:
            # RegisterHotKey consumes chords before Tk can see them, so the live
            # manager must be stopped for the whole dialog lifetime.
            self.logger.info("Stopping hotkeys while the settings dialog is open.")
            self.hotkeys.stop()

        def on_capture_end() -> None:
            self.logger.info("Restarting hotkeys after the settings dialog closed.")
            try:
                activation = self.hotkeys.start()
            except Exception:
                self.logger.exception(
                    "Hotkeys could not be restarted after the settings dialog."
                )
                return
            if not activation.successful:
                failed = ", ".join(
                    display_hotkey(combo) for combo in activation.failed
                )
                self.logger.error(
                    "Hotkeys restarted with failures after settings dialog: %s.",
                    failed,
                )

        self.hotkey_settings_window.show(
            self.settings.hotkeys,
            self.set_hotkeys,
            self.settings.language_favorites,
            on_capture_begin=on_capture_begin,
            on_capture_end=on_capture_end,
        )

    def open_language_settings(self) -> None:
        self.language_settings_window.show(
            self.settings.language_mode,
            self.settings.language_favorites,
            self.set_language_preferences,
        )

    def open_permission_setup(self) -> None:
        if sys.platform == "darwin":
            self.permission_setup_window.show()

    def _microphone_readiness_error(self) -> str | None:
        if sys.platform != "darwin":
            return None
        status = get_permission_snapshot().microphone
        if status.ready:
            return None
        self.open_permission_setup()
        if status.state is PermissionState.MISCONFIGURED:
            return (
                "This Speech build is missing the macOS audio-input entitlement. "
                "Install a correctly signed build."
            )
        return (
            "Microphone permission is not ready. Use Permissions in the Speech "
            "menu, then recheck."
        )

    def open_settings_file(self) -> None:
        try:
            settings_path = app_data_dir() / "settings.json"
            if not settings_path.exists():
                save_settings(self.settings)
            _open_path(settings_path)
            self.notify(
                APP_NAME,
                "Use the Language, Microphone, and Hotkey menus for live changes. "
                "Restart after editing model or advanced settings.",
            )
        except Exception:
            self._handle_error("Settings file could not be opened.")

    def open_log_folder(self) -> None:
        try:
            _open_path(app_data_dir() / "logs")
        except Exception:
            self._handle_error("Log folder could not be opened.")

    def run_diagnostics(self) -> None:
        thread = threading.Thread(
            target=self._run_diagnostics_worker,
            name="winwhisper-diagnostics-worker",
            daemon=True,
        )
        thread.start()

    def check_for_updates(self) -> None:
        self.update_coordinator.check_for_updates(manual=True)

    def notify(self, title: str, message: str) -> None:
        self.tray.notify(title, message)

    def _on_device_fallback(self, device: str, compute_type: str) -> None:
        """Surface a silent CPU fallback; otherwise it only shows up as slowness."""
        self.logger.warning(
            "Configured device %s (compute_type=%s) is unavailable; using the CPU.",
            device,
            compute_type,
        )
        self.notify(
            APP_NAME,
            f"{device} is unavailable on this machine. Speech is transcribing on "
            "the CPU instead.",
        )

    def set_status(self, status: Status) -> None:
        with self._lock:
            self._status = status
        self.tray.set_status(status)

    def is_recording(self) -> bool:
        return self.recorder.is_recording()

    def _current_microphone_level(self) -> float:
        with self._lock:
            microphone_test = self._microphone_test
        if microphone_test is not None:
            return microphone_test.current_level()
        return self.recorder.current_level()

    def _on_max_recording_duration(self) -> None:
        # Called from the audio callback; hop to a worker immediately.
        threading.Thread(
            target=self._handle_max_recording_duration,
            name="winwhisper-max-duration-stop",
            daemon=True,
        ).start()

    def _toggle_favorite_language(self, index: int) -> None:
        favorites = self.settings.language_favorites
        language = favorites[index] if index < len(favorites) else None
        if language is None:
            self.logger.warning(
                "Quick language %s was triggered without a favorite.", index + 1
            )
            self.notify(
                APP_NAME,
                f"Set Favorite {index + 1} in Language Settings before using this hotkey.",
            )
            return
        self.toggle(language)

    def _stop_microphone_test(
        self,
        expected_test: MicrophoneTest | None = None,
        *,
        completed: bool = False,
        notify: bool = True,
    ) -> bool:
        peak_level = 0.0
        stop_failed = False
        with self._lock:
            microphone_test = self._microphone_test
            if microphone_test is None or (
                expected_test is not None and microphone_test is not expected_test
            ):
                return False
            cancel = self._microphone_test_cancel
            shutdown = self._shutdown
            if cancel is not None:
                cancel.set()
            stop_complete = self._new_microphone_stop_completion()
            self._start_microphone_stop_watchdog(stop_complete)
            try:
                try:
                    peak_level = microphone_test.stop()
                finally:
                    stop_complete.set()
            except Exception:
                stop_failed = True
                self.logger.exception("Microphone test failed to stop cleanly.")
            finally:
                self._microphone_test = None
                self._microphone_test_cancel = None
                # Hide before another toggle can begin a real dictation and
                # publish a new recording overlay.
                self.recording_overlay.hide()
                if not shutdown:
                    self.set_status(STATUS_IDLE)

        if stop_failed and notify and not shutdown:
            self.notify(APP_NAME, "Microphone test could not stop cleanly.")

        if notify and not shutdown and not stop_failed:
            if peak_level >= MICROPHONE_TEST_SIGNAL_THRESHOLD:
                self.notify(APP_NAME, "Microphone test complete. Signal detected.")
            elif completed:
                self.notify(
                    APP_NAME,
                    "No sound detected. Check the microphone, its permission, "
                    "and the selected input.",
                )
            else:
                self.notify(APP_NAME, "Microphone test stopped before sound was detected.")
        return True

    def _handle_max_recording_duration(self) -> None:
        if self._request_stop():
            self.logger.warning("Max recording duration reached; stopping dictation.")
            self.notify(APP_NAME, "Max recording length reached; stopping.")
        else:
            self.logger.info("Max recording duration reached after recording had stopped.")

    def _request_stop(self, hide_overlay_if_idle: bool = False) -> bool:
        beep: tuple[int, int] | None = None
        hide_overlay = False
        with self._lock:
            if self._processing:
                self.logger.info("Ignoring stop while dictation is being processed.")
                hide_overlay = hide_overlay_if_idle
            elif not self.recorder.is_recording():
                hide_overlay = hide_overlay_if_idle
            else:
                beep = self._begin_stop_locked()

        if hide_overlay:
            self.recording_overlay.hide()
        if beep is not None:
            self._beep(*beep)
        return beep is not None

    def _begin_stop_locked(self) -> tuple[int, int]:
        language_mode = self._recording_language_mode or self.settings.language_mode
        self._processing = True
        stop_complete = self._new_microphone_stop_completion()
        self.logger.info(
            "Stop requested; switching to transcribing UI (language_mode=%s; model_loaded=%s).",
            language_mode,
            self.transcriber.is_model_loaded(),
        )
        # Overlay update intentionally stays inside the lock so the UI state
        # cannot race a second stop/hotkey before the worker is armed.
        self.recording_overlay.show_transcribing()
        worker = threading.Thread(
            target=self._stop_and_process,
            args=(language_mode, stop_complete),
            name="winwhisper-dictation-worker",
            daemon=True,
        )
        worker.start()
        self._start_microphone_stop_watchdog(stop_complete)
        return (440, 120)

    def _new_microphone_stop_completion(self) -> threading.Event:
        stop_complete = threading.Event()
        with self._lock:
            self._microphone_stop_complete = stop_complete
        return stop_complete

    def _start_microphone_stop_watchdog(
        self,
        stop_complete: threading.Event,
    ) -> None:
        _RealThread(
            target=self._watch_microphone_stop,
            args=(stop_complete,),
            name="winwhisper-microphone-stop-watch",
            daemon=True,
        ).start()

    def _watch_microphone_stop(self, stop_complete: threading.Event) -> None:
        if stop_complete.wait(MICROPHONE_STOP_TIMEOUT_SECONDS):
            return
        self._handle_microphone_stop_timeout()

    def _handle_microphone_stop_timeout(self) -> None:
        self.logger.critical(
            "Microphone shutdown did not complete within %.0fs; forcing process exit.",
            MICROPHONE_STOP_TIMEOUT_SECONDS,
        )
        try:
            self.notify(
                APP_NAME,
                "Microphone shutdown is stuck. Speech must close to release it.",
            )
        except Exception:
            self.logger.exception("Could not notify about stuck microphone shutdown.")
        _hard_exit(MICROPHONE_STOP_TIMEOUT_EXIT_CODE)

    def _start_model_warmup(self) -> None:
        thread = threading.Thread(
            target=self._warm_model_worker,
            name="winwhisper-model-warmup",
            daemon=True,
        )
        thread.start()

    def _warm_model_worker(self) -> None:
        downloading = False
        try:
            size = str(self.settings.model_size)
            cached = is_model_cached(size)
            if cached is False:
                downloading = True
                mb = MODEL_DOWNLOAD_SIZES_MB.get(
                    size, MODEL_DOWNLOAD_SIZES_MB["small"]
                )
                self.notify(
                    APP_NAME,
                    f"Downloading speech model {size} ({mb} MB). "
                    "The first dictation may take a minute.",
                )
                self.set_status(STATUS_DOWNLOADING_MODEL)
            self.logger.info(
                "Preloading speech model in background (model_size=%s; device=%s).",
                self.settings.model_size,
                self.settings.device,
            )
            self.transcriber.ensure_model_loaded()
            self.logger.info("Speech model preload finished.")
        except Exception:
            self.logger.exception(
                "Speech model preload failed; first dictation will retry the load."
            )
        finally:
            if downloading and self._status == STATUS_DOWNLOADING_MODEL:
                self.set_status(STATUS_IDLE)

    def _stop_and_process(
        self,
        language_mode: LanguageMode,
        stop_complete: threading.Event,
    ) -> None:
        audio_path: Path | None = None
        failed = False
        progress_cancel = threading.Event()
        stats: Any = None
        stop_ms = 0
        transcribe_ms = 0
        clean_ms = 0
        paste_ms = 0

        try:
            self.logger.info("Stopping microphone capture...")
            stop_started = time.perf_counter()
            try:
                audio_path = self.recorder.stop_recording()
            finally:
                stop_complete.set()
            stop_elapsed = time.perf_counter() - stop_started
            stop_ms = int(stop_elapsed * 1000)
            stats = getattr(self.recorder, "last_take_stats", lambda: None)()
            if audio_path is None:
                self.logger.info("Recording already stopped; skipping dictation.")
                return

            audio_size = audio_path.stat().st_size if audio_path.exists() else 0
            self.logger.info(
                "Microphone stopped in %.2fs; audio_file=%s; bytes=%s.",
                stop_elapsed,
                audio_path.name,
                audio_size,
            )

            if stats is not None and stats.frames == 0:
                label = stats.device_label
                self.logger.info("Nothing was captured from %s", label)
                self.notify(
                    APP_NAME,
                    f"Nothing was captured from {label}. Open Microphone and "
                    "pick System Default or another device.",
                )
                try:
                    audio_path.unlink(missing_ok=True)
                except Exception:
                    self.logger.warning("Temporary audio file could not be deleted.")
                audio_path = None
                return

            self.set_status(STATUS_TRANSCRIBING)
            self._start_slow_transcription_watcher(progress_cancel)

            transcribe_started = time.perf_counter()
            result = self.transcriber.transcribe(audio_path, language_mode)
            transcribe_ms = int((time.perf_counter() - transcribe_started) * 1000)
            self._delete_audio(audio_path)
            audio_path = None

            if not result.text.strip():
                self._notify_empty_transcription(
                    stats,
                    "No speech detected; transcription text was empty.",
                )
                return

            self.logger.info("Cleaning transcription text (mode=%s)...", self.settings.cleanup_mode)
            clean_started = time.perf_counter()
            cleaned = clean_text(
                result.text,
                self.settings.cleanup_mode,
                self.settings.custom_vocabulary,
            )
            with self._lock:
                trim_phrase = self._pending_trim_phrase
            if trim_phrase:
                cleaned = trim_trailing_phrase(cleaned, trim_phrase)
            clean_ms = int((time.perf_counter() - clean_started) * 1000)
            if not cleaned.strip():
                self._notify_empty_transcription(
                    stats,
                    "No speech detected; cleaned transcription text was empty.",
                )
                return

            self.set_status(STATUS_PASTING)
            self.logger.info("Restoring focus and pasting transcription...")
            paste_started = time.perf_counter()
            restored_target = self._restore_paste_target()
            if (
                sys.platform == "win32"
                and not restored_target
                and foreground_matches(self._paste_target_window) is False
            ):
                copy_text_to_clipboard(cleaned)
                self.logger.warning(
                    "Target window changed; text left on the clipboard."
                )
                self.notify(
                    APP_NAME,
                    "Target window changed. The text is on the clipboard; "
                    "press Ctrl+V to paste it.",
                )
                paste_ms = int((time.perf_counter() - paste_started) * 1000)
                return
            if sys.platform.startswith("linux") and not restored_target:
                shortcut = self._paste_shortcut()
                if copy_text_to_clipboard(cleaned):
                    self.notify(
                        APP_NAME,
                        f"Automatic paste failed. Try {_shortcut_label(shortcut)}.",
                    )
                else:
                    self.notify(
                        APP_NAME,
                        "Automatic paste failed, and the transcription could not "
                        "be copied.",
                    )
                paste_ms = int((time.perf_counter() - paste_started) * 1000)
                return
            shortcut = self._paste_shortcut()
            if sys.platform == "win32":
                deadline = time.monotonic() + 1.0
                while windows_modifier_state():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    time.sleep(min(0.03, remaining))
            if insert_text(cleaned, shortcut=shortcut):
                self.logger.info(
                    "Paste shortcut sent (%s); dictation text remains on clipboard.",
                    shortcut,
                )
            else:
                self.logger.warning("Automatic paste failed; dictation may still be on clipboard.")
                self.notify(
                    APP_NAME,
                    f"Automatic paste failed. Try {_shortcut_label(shortcut)}.",
                )
            paste_ms = int((time.perf_counter() - paste_started) * 1000)
        except ModelDownloadError as exc:
            failed = True
            self._handle_error(str(exc))
        except Exception:
            failed = True
            self._handle_error("Dictation failed.")
        finally:
            self._log_take_timing(
                stats=stats,
                stop_ms=stop_ms,
                transcribe_ms=transcribe_ms,
                clean_ms=clean_ms,
                paste_ms=paste_ms,
            )
            progress_cancel.set()
            if audio_path is not None:
                self._delete_audio(audio_path)
            self._stop_stop_monitor()
            with self._lock:
                self._processing = False
                self._recording_language_mode = None
                self._paste_target_window = None
                self._paste_target_process_name = None
                self._overlay_anchor = None
                self._pending_trim_phrase = None
                self._recording_started_by_wake_word = False
                wake_listener = self._wake_listener
                wake_enabled = self.settings.wake_word_enabled
                shutdown = self._shutdown
            if (
                wake_listener is not None
                and wake_enabled
                and not shutdown
            ):
                try:
                    wake_listener.resume()
                except Exception:
                    self.logger.exception("Wake-word listener failed to resume.")
            # Synthetic paste and missed key-ups can leave a phantom trigger key
            # "down", which blocks the next take. Clear only the trigger tracking
            # so a chord the user is still physically holding keeps matching.
            self.hotkeys.reset_trigger_state()
            self.recording_overlay.hide()
            if not failed and not shutdown:
                self.set_status(STATUS_IDLE)

    def _start_slow_transcription_watcher(self, cancel: threading.Event) -> None:
        def watch() -> None:
            if cancel.wait(SLOW_TRANSCRIPTION_NOTIFY_SECONDS):
                return
            self._notify_slow_transcription()

        _RealThread(
            target=watch,
            name="winwhisper-slow-transcription-watch",
            daemon=True,
        ).start()

    def _notify_slow_transcription(self) -> None:
        with self._lock:
            still_processing = self._processing
            model_loaded = self.transcriber.is_model_loaded()
        if not still_processing:
            return
        if sys.platform.startswith("linux"):
            cause = "Local inference can be compute-bound; a smaller model_size is faster."
            notify_hint = "first run and local inference can take longer."
        else:
            cause = "Antivirus real-time scanning can slow model load or CPU inference."
            notify_hint = "first run or antivirus scanning can take longer."
        self.logger.warning(
            "Transcription still running after %.0fs (model_loaded=%s). %s",
            SLOW_TRANSCRIPTION_NOTIFY_SECONDS,
            model_loaded,
            cause,
        )
        self.notify(
            APP_NAME,
            f"Still transcribing… {notify_hint}",
        )

    def _restore_paste_target(self) -> bool:
        with self._lock:
            target_window = self._paste_target_window

        if target_window is None:
            return True

        if restore_foreground_window(target_window):
            self.logger.info("Restored target window before paste.")
            return True

        self.logger.warning("Could not restore target window before paste.")
        return False

    def _paste_shortcut(self) -> PasteShortcut:
        with self._lock:
            process_name = self._paste_target_process_name

        return resolve_paste_shortcut(self.settings.paste_mode, process_name)

    def _run_diagnostics_worker(self) -> None:
        try:
            output = io.StringIO()
            with redirect_stdout(output):
                run_diagnostics_report()
            report = output.getvalue().strip()
            self.logger.info("Diagnostics report:\n%s", report or "(no output)")
            self.notify(
                APP_NAME,
                "Diagnostics ran. Report written to log.",
            )
        except Exception:
            self._handle_error("Diagnostics failed.")

    def _delete_audio(self, audio_path: Path) -> None:
        if not self.settings.delete_audio_after_transcription:
            return

        try:
            audio_path.unlink(missing_ok=True)
        except Exception:
            self.logger.warning("Temporary audio file could not be deleted.")

    def _notify_empty_transcription(self, stats: Any, empty_log: str) -> None:
        if stats is not None and stats.peak == 0.0:
            label = stats.device_label
            self.logger.info("%s delivered silence.", label)
            self.notify(
                APP_NAME,
                f"{label} delivered silence. Check the microphone or pick another one.",
            )
            return
        self.logger.info(empty_log)
        self.notify(APP_NAME, "No speech detected")

    def _log_take_timing(
        self,
        *,
        stats: Any,
        stop_ms: int,
        transcribe_ms: int,
        clean_ms: int,
        paste_ms: int,
    ) -> None:
        to_stream_ms = int(
            getattr(self.recorder, "last_to_stream_ms", lambda: 0)()
        )
        if stats is None:
            first_block_display: int | None = None
            record_s = 0.0
            frames = 0
            peak = 0.0
            device = "unknown"
            refresh_ms: float | None = None
            host_api = "unknown"
        else:
            first_block_display = (
                int(stats.first_block_ms)
                if stats.first_block_ms is not None
                else None
            )
            record_s = float(stats.seconds)
            frames = int(stats.frames)
            peak = float(stats.peak)
            device = str(stats.device_label)
            refresh_ms = getattr(stats, "refresh_ms", None)
            host_api = str(getattr(stats, "host_api", "unknown"))
        self.logger.info(
            "Take timing: to_stream_ms=%d first_block_ms=%s record_s=%.1f "
            "stop_ms=%d transcribe_ms=%d clean_ms=%d paste_ms=%d "
            "frames=%d peak=%.3f device=%s refresh_ms=%s host_api=%s",
            to_stream_ms,
            first_block_display,
            record_s,
            stop_ms,
            transcribe_ms,
            clean_ms,
            paste_ms,
            frames,
            peak,
            device,
            refresh_ms,
            host_api,
        )

    def _handle_error(self, message: str) -> None:
        self.logger.exception(message)
        self._beep(220, 350)
        self.set_status(STATUS_ERROR)
        self.notify(APP_NAME, message)

    def _sync_microphone_label(self) -> None:
        label = SYSTEM_DEFAULT_INPUT_LABEL
        name = self.settings.audio_input_device_name
        index = self.settings.audio_input_device
        if name is not None:
            label = name
            try:
                devices = list_audio_input_devices()
                for group in group_physical_input_devices(devices):
                    if any(
                        row.name == name
                        and row.host_api
                        == (self.settings.audio_input_device_host_api or "")
                        for row in group.rows
                    ):
                        label = group.label
                        break
            except Exception:
                self.logger.exception("Could not resolve the microphone tooltip label.")
        elif index is not None:
            label = f"Unavailable microphone [{index}]"
        set_label = getattr(self.tray, "set_microphone_label", None)
        if callable(set_label):
            set_label(label)

    def _maybe_toast_microphone_fallback(self) -> None:
        resolution = getattr(self.recorder, "last_resolution", None)
        if resolution is None:
            return
        fallback = bool(getattr(resolution, "fallback", False))
        previous = self._previous_mic_resolution_fallback
        self._previous_mic_resolution_fallback = fallback
        if not fallback or previous:
            return
        saved_name = self.settings.audio_input_device_name
        if saved_name is None:
            reason = (
                f"the saved microphone [{self.settings.audio_input_device}] "
                "is unavailable"
            )
        else:
            reason = f"{saved_name} is unavailable"
        self.notify(APP_NAME, f"Using System Default because {reason}")

    def _beep(self, frequency: int, duration_ms: int) -> None:
        if sys.platform == "win32":
            try:
                import winsound

                winsound.Beep(frequency, duration_ms)
            except Exception as exc:
                self.logger.warning("Beep failed with %s.", exc.__class__.__name__)
            return

        if sys.platform == "darwin":
            # Map the cue tones onto system sounds: high = start, mid = stop,
            # low = error.
            if frequency >= 800:
                sound = "Tink"
            elif frequency >= 300:
                sound = "Pop"
            else:
                sound = "Basso"
            try:
                import subprocess

                subprocess.Popen(
                    ["afplay", f"/System/Library/Sounds/{sound}.aiff"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as exc:
                self.logger.warning("Beep failed with %s.", exc.__class__.__name__)
            return

        # Linux: no reliable beep without extra dependencies; stay silent.


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=APP_NAME)
    parser.add_argument("--version", action="store_true", help="Print version and exit.")
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="Print diagnostics and exit.",
    )
    args = parser.parse_args(argv)

    if args.version:
        _attach_parent_console_for_cli()
        print(__version__)
        return _finish_cli(0)

    logger = get_logger(__name__)
    _apply_startup_mitigations(logger)

    if args.diagnostics:
        _attach_parent_console_for_cli()
        run_diagnostics_report()
        return _finish_cli(0)

    if not _acquire_single_instance():
        logger.warning("Another %s instance is already running; exiting.", APP_NAME)
        _attach_parent_console_for_cli()
        print(f"{APP_NAME} is already running.", file=sys.stderr)
        return _finish_cli(0)

    logger.info(
        "%s %s starting (settings=%s).",
        APP_NAME,
        __version__,
        app_data_dir() / "settings.json",
    )

    report = load_settings_report()
    settings = report.settings
    _adopt_audio_input_identity(settings, logger)
    logger.info(
        "Settings loaded: model_size=%s; device=%s; compute_type=%s; "
        "language_mode=%s; cleanup_mode=%s; paste_mode=%s; "
        "delete_audio_after_transcription=%s.",
        settings.model_size,
        settings.device,
        settings.compute_type,
        settings.language_mode,
        settings.cleanup_mode,
        settings.paste_mode,
        settings.delete_audio_after_transcription,
    )

    controller = AppController(
        settings,
        notices=report.notices,
        first_run=report.first_run,
    )
    try:
        controller.run()
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
        controller.stop()
    except Exception:
        logger.exception("%s exited after an unhandled error.", APP_NAME)
        controller.stop()
        return 1
    return 0


def _acquire_single_instance() -> bool:
    """Return True if this process owns the platform single-instance lock."""
    global _mutex_handle, _single_instance_lock_handle
    if os.name != "nt":
        handle: Any | None = None
        try:
            import errno
            import fcntl

            lock_dir = app_data_dir()
            lock_dir.mkdir(parents=True, exist_ok=True)
            handle = (lock_dir / _SINGLE_INSTANCE_LOCK_FILE_NAME).open("a")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                try:
                    handle.close()
                except Exception:
                    pass
                return False
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EAGAIN):
                    try:
                        handle.close()
                    except Exception:
                        pass
                    return False
                raise

            _single_instance_lock_handle = handle
            return True
        except Exception:
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
            return True

    try:
        # Private handle: never set argtypes on the shared ctypes.windll cache.
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [
            wintypes_lpsecurityattributes(),
            ctypes.c_bool,
            ctypes.c_wchar_p,
        ]
        kernel32.CreateMutexW.restype = ctypes.c_void_p

        handle = kernel32.CreateMutexW(None, False, _SINGLE_INSTANCE_MUTEX_NAME)
        if not handle:
            return True  # Fail open if mutex cannot be created.

        # use_last_error=True captures the error at call time; read it via
        # ctypes.get_last_error() (a raw GetLastError() call is unreliable here).
        error = int(ctypes.get_last_error())
        # ERROR_ALREADY_EXISTS
        if error == 183:
            kernel32.CloseHandle(handle)
            return False

        _mutex_handle = handle
        return True
    except Exception:
        return True


def wintypes_lpsecurityattributes() -> Any:
    return ctypes.c_void_p


def _apply_startup_mitigations(logger: logging.Logger) -> None:
    _drop_invalid_sslkeylogfile(logger)
    _inject_truststore(logger)


def _attach_parent_console_for_cli() -> None:
    if os.name != "nt":
        return
    if sys.stdout is not None and sys.stderr is not None:
        return

    try:
        import ctypes as ct

        attach_parent_process = ct.c_uint(-1).value
        ct.windll.kernel32.AttachConsole(attach_parent_process)
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)
    except Exception:
        pass


def _finish_cli(exit_code: int) -> int:
    try:
        if sys.stdout is not None:
            sys.stdout.flush()
        if sys.stderr is not None:
            sys.stderr.flush()
    except Exception:
        pass

    if getattr(sys, "frozen", False):
        os._exit(exit_code)
    return exit_code


def _drop_invalid_sslkeylogfile(logger: logging.Logger) -> None:
    """Strip TLS key-log paths that break OpenSSL under antivirus interception.

    Products such as Norton sometimes set SSLKEYLOGFILE to a Win32 device
    namespace path. OpenSSL then crashes with "no OPENSSL_Applink". Speech never
    needs this variable, so unsafe or non-writable values are removed at boot.
    """
    value = os.environ.get("SSLKEYLOGFILE")
    if not value:
        return

    if value.startswith("\\\\.\\"):
        os.environ.pop("SSLKEYLOGFILE", None)
        logger.warning(
            "Removed antivirus-style SSLKEYLOGFILE device path before TLS startup (%s).",
            value,
        )
        return

    if _is_writable_regular_file(value):
        return

    os.environ.pop("SSLKEYLOGFILE", None)
    logger.warning("Removed invalid SSLKEYLOGFILE value before TLS startup (%s).", value)


def _is_writable_regular_file(path_value: str) -> bool:
    if path_value.startswith("\\\\.\\"):
        # Win32 device namespace, as used by antivirus TLS interceptors such
        # as Norton. os.stat reports these as writable regular files, but
        # OpenSSL crashes with "no OPENSSL_Applink" when it writes to them.
        return False
    try:
        path = Path(path_value)
        return path.is_file() and os.access(path, os.W_OK)
    except (OSError, ValueError):
        return False


def _inject_truststore(logger: logging.Logger) -> None:
    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception as exc:
        logger.warning(
            "truststore SSL injection failed with %s; continuing with default trust.",
            exc.__class__.__name__,
        )


def _open_path(path: Path) -> None:
    """Open a file with the platform's default application."""
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return

    import subprocess

    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen(
        [opener, str(path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _macos_app_bundle_path(executable: str | Path) -> PurePosixPath | None:
    """Return the .app bundle for a packaged MacOS executable, if any.

    Expected layout: ``<Name>.app/Contents/MacOS/<executable>``.
    """
    path = PurePosixPath(str(executable))
    if path.parent.name != "MacOS":
        return None
    if path.parent.parent.name != "Contents":
        return None
    app_path = path.parent.parent.parent
    if not app_path.name.endswith(".app"):
        return None
    return app_path


def _launch_macos_relaunch_helper(
    *,
    pid: int,
    app_path: Path | PurePosixPath,
) -> None:
    """Start a detached shell that reopens the app after ``pid`` exits.

    PID and app path are passed as separate argv values so spaces and shell
    metacharacters in the path are never interpolated into shell source.
    """
    import subprocess

    # $1 = pid, $2 = .app path (see argv after -c below).
    script = (
        'while /bin/kill -0 "$1" 2>/dev/null; do /bin/sleep 0.2; done; '
        'exec /usr/bin/open -n "$2"'
    )
    subprocess.Popen(
        [
            "/bin/sh",
            "-c",
            script,
            "speech-hotkey-relaunch",
            str(pid),
            str(app_path),
        ],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


def _queue_macos_main_operation(operation: Callable[[], None]) -> None:
    """Queue work on AppKit's main operation queue (after the current modal)."""
    from Foundation import NSOperationQueue

    NSOperationQueue.mainQueue().addOperationWithBlock_(operation)


def _shortcut_label(shortcut: PasteShortcut) -> str:
    if shortcut == "cmd_v":
        return "Cmd+V"
    if shortcut == "ctrl_shift_v":
        return "Ctrl+Shift+V"
    return "Ctrl+V"


if __name__ == "__main__":
    raise SystemExit(main())
