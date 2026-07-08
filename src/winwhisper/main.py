from __future__ import annotations

import argparse
import ctypes
import io
import logging
import os
import sys
import threading
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Literal

from . import __version__
from .branding import APP_NAME
from .config import Settings, app_data_dir, load_settings, save_settings
from .diagnostics import run_diagnostics as run_diagnostics_report
from .focus import (
    ScreenPoint,
    get_cursor_anchor,
    get_foreground_window,
    get_window_process_name,
    restore_foreground_window,
)
from .formatter import clean_text
from .hotkeys import HotkeyManager
from .inserter import PasteShortcut, insert_text, resolve_paste_shortcut
from .logger import get_logger
from .overlay import RecordingOverlay
from .recorder import Recorder
from .transcriber import Transcriber
from .tray import TrayApp
from .update_controller import UpdateCoordinator

Status = Literal["Idle", "Recording", "Transcribing", "Pasting", "Error"]
LanguageMode = Literal["auto", "en", "es"]

STATUS_IDLE: Status = "Idle"
STATUS_RECORDING: Status = "Recording"
STATUS_TRANSCRIBING: Status = "Transcribing"
STATUS_PASTING: Status = "Pasting"
STATUS_ERROR: Status = "Error"

_SINGLE_INSTANCE_MUTEX_NAME = "Local\\SpeechSingleInstanceMutex"
_mutex_handle: Any | None = None


class AppController:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.logger = get_logger(__name__)
        self.recorder = Recorder(on_max_duration=self._on_max_recording_duration)
        self.transcriber = Transcriber(settings)
        self.tray = TrayApp(self)
        self.recording_overlay = RecordingOverlay(
            self.stop_from_overlay,
            self.recorder.current_level,
        )
        self.hotkeys = HotkeyManager(settings.hotkeys, self.on_hotkey)
        self._lock = threading.RLock()
        self._status: Status = STATUS_IDLE
        self._processing = False
        self._shutdown = False
        self._recording_language_mode: LanguageMode | None = None
        self._paste_target_window: int | None = None
        self._paste_target_process_name: str | None = None
        self._overlay_anchor: ScreenPoint | None = None
        self.update_coordinator = UpdateCoordinator(
            self.settings,
            self.notify,
            self.exit_app,
            self.logger,
        )

    def run(self) -> None:
        self.set_status(STATUS_IDLE)
        try:
            self.hotkeys.start()
            self.logger.info("Hotkey listener started.")
        except Exception:
            self._handle_error("Hotkey listener failed to start.")

        try:
            self.update_coordinator.maybe_check_for_updates()
        except Exception as exc:
            self.logger.warning(
                "Automatic update check could not start with %s.",
                exc.__class__.__name__,
            )

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

        if self.recorder.is_recording():
            try:
                self.recording_overlay.hide()
                audio_path = self.recorder.stop_recording()
                if audio_path is not None:
                    self._delete_audio(audio_path)
            except Exception:
                self.logger.exception("Active recording failed to stop during shutdown.")

        self.recording_overlay.stop()
        self.tray.stop()
        self.logger.info("%s stopped.", APP_NAME)

    def exit_app(self) -> None:
        self.logger.info("Exit requested.")
        self.stop()

    def stop_from_overlay(self) -> None:
        with self._lock:
            if self._processing or not self.recorder.is_recording():
                self.recording_overlay.hide()
                return
        self.toggle()

    def on_hotkey(self, action: str) -> None:
        if action == "toggle":
            self.toggle()
            return
        if action == "force_en":
            self.toggle("en")
            return
        if action == "force_es":
            self.toggle("es")
            return

        self.logger.warning("Unknown hotkey action %s.", action)

    def toggle(self, language_override: LanguageMode | None = None) -> None:
        beep: tuple[int, int] | None = None
        start_failed = False

        with self._lock:
            if self._processing:
                self.logger.info("Ignoring toggle while dictation is being processed.")
                return

            if self.recorder.is_recording():
                language_mode = self._recording_language_mode or self.settings.language_mode
                self._processing = True
                self.logger.info(
                    "Recording stopped; transcribing (language_mode=%s).",
                    language_mode,
                )
                self.recording_overlay.show_transcribing()
                worker = threading.Thread(
                    target=self._stop_and_process,
                    args=(language_mode,),
                    name="winwhisper-dictation-worker",
                    daemon=True,
                )
                worker.start()
                beep = (440, 120)
            else:
                language_mode = language_override or self.settings.language_mode
                self._paste_target_window = get_foreground_window()
                self._paste_target_process_name = get_window_process_name(
                    self._paste_target_window
                )
                self._overlay_anchor = get_cursor_anchor(self._paste_target_window)
                try:
                    self.recorder.start_recording()
                except Exception:
                    self._paste_target_window = None
                    self._paste_target_process_name = None
                    self._overlay_anchor = None
                    start_failed = True
                else:
                    self._recording_language_mode = language_mode
                    self.logger.info("Recording started (language_mode=%s).", language_mode)
                    self.recording_overlay.show(self._overlay_anchor)
                    self.set_status(STATUS_RECORDING)
                    beep = (880, 120)

        if start_failed:
            self._handle_error("Recording failed to start.")
            return
        if beep is not None:
            self._beep(*beep)

    def set_language_mode(self, mode: str) -> None:
        if mode not in {"auto", "en", "es"}:
            self.logger.warning("Ignoring unsupported language mode %s.", mode)
            return

        self.settings.language_mode = mode  # type: ignore[assignment]
        save_settings(self.settings)
        self.logger.info("Language mode set to %s.", mode)

    def set_cleanup_mode(self, mode: str) -> None:
        if mode not in {"none", "basic", "llm"}:
            self.logger.warning("Ignoring unsupported cleanup mode %s.", mode)
            return

        self.settings.cleanup_mode = mode  # type: ignore[assignment]
        save_settings(self.settings)
        self.logger.info("Cleanup mode set to %s.", mode)

    def open_settings_file(self) -> None:
        try:
            save_settings(self.settings)
            os.startfile(str(app_data_dir() / "settings.json"))  # type: ignore[attr-defined]
            self.notify(
                APP_NAME,
                "Restart Speech after editing hotkeys or model settings.",
            )
        except Exception:
            self._handle_error("Settings file could not be opened.")

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

    def set_status(self, status: Status) -> None:
        with self._lock:
            self._status = status
        self.tray.set_status(status)

    def is_recording(self) -> bool:
        return self.recorder.is_recording()

    def _on_max_recording_duration(self) -> None:
        # Called from the audio callback; hop to a worker immediately.
        threading.Thread(
            target=self._handle_max_recording_duration,
            name="winwhisper-max-duration-stop",
            daemon=True,
        ).start()

    def _handle_max_recording_duration(self) -> None:
        self.logger.warning("Max recording duration reached; stopping dictation.")
        self.notify(APP_NAME, "Max recording length reached; stopping.")
        self.toggle()

    def _stop_and_process(self, language_mode: LanguageMode) -> None:
        audio_path: Path | None = None
        failed = False

        try:
            audio_path = self.recorder.stop_recording()
            if audio_path is None:
                self.logger.info("Recording already stopped; skipping dictation.")
                return

            self.set_status(STATUS_TRANSCRIBING)
            result = self.transcriber.transcribe(audio_path, language_mode)
            self._delete_audio(audio_path)
            audio_path = None

            if not result.text.strip():
                self.logger.info("No speech detected; transcription text was empty.")
                self.notify(APP_NAME, "No speech detected")
                return

            cleaned = clean_text(result.text, self.settings.cleanup_mode)
            if not cleaned.strip():
                self.logger.info("No speech detected; cleaned transcription text was empty.")
                self.notify(APP_NAME, "No speech detected")
                return

            self.set_status(STATUS_PASTING)
            self._restore_paste_target()
            shortcut = self._paste_shortcut()
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
        except Exception:
            failed = True
            self._handle_error("Dictation failed.")
        finally:
            if audio_path is not None:
                self._delete_audio(audio_path)
            with self._lock:
                self._processing = False
                self._recording_language_mode = None
                self._paste_target_window = None
                self._paste_target_process_name = None
                self._overlay_anchor = None
                shutdown = self._shutdown
            self.recording_overlay.hide()
            if not failed and not shutdown:
                self.set_status(STATUS_IDLE)

    def _restore_paste_target(self) -> None:
        with self._lock:
            target_window = self._paste_target_window

        if target_window is None:
            return

        if restore_foreground_window(target_window):
            self.logger.info("Restored target window before paste.")
        else:
            self.logger.warning("Could not restore target window before paste.")

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

    def _handle_error(self, message: str) -> None:
        self.logger.exception(message)
        self._beep(220, 350)
        self.set_status(STATUS_ERROR)
        self.notify(APP_NAME, message)

    def _beep(self, frequency: int, duration_ms: int) -> None:
        try:
            import winsound

            winsound.Beep(frequency, duration_ms)
        except Exception as exc:
            self.logger.warning("Beep failed with %s.", exc.__class__.__name__)


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

    logger.info("%s starting.", APP_NAME)

    settings = load_settings()
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

    controller = AppController(settings)
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
    """Return True if this process owns the single-instance mutex."""
    global _mutex_handle
    if os.name != "nt":
        return True

    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [
            wintypes_lpsecurityattributes(),
            ctypes.c_bool,
            ctypes.c_wchar_p,
        ]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.GetLastError.restype = ctypes.c_ulong

        handle = kernel32.CreateMutexW(None, False, _SINGLE_INSTANCE_MUTEX_NAME)
        if not handle:
            return True  # Fail open if mutex cannot be created.

        error = int(kernel32.GetLastError())
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
    value = os.environ.get("SSLKEYLOGFILE")
    if not value:
        return

    if _is_writable_regular_file(value):
        return

    os.environ.pop("SSLKEYLOGFILE", None)
    logger.warning("Removed invalid SSLKEYLOGFILE value before TLS startup.")


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


def _shortcut_label(shortcut: PasteShortcut) -> str:
    if shortcut == "ctrl_shift_v":
        return "Ctrl+Shift+V"
    return "Ctrl+V"


if __name__ == "__main__":
    raise SystemExit(main())
