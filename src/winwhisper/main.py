from __future__ import annotations

import io
import logging
import os
import threading
from contextlib import redirect_stdout
from pathlib import Path
from typing import Literal

from .config import Settings, app_data_dir, load_settings, save_settings
from .diagnostics import run_diagnostics as run_diagnostics_report
from .formatter import clean_text
from .hotkeys import HotkeyManager
from .inserter import insert_text
from .logger import get_logger
from .recorder import Recorder
from .transcriber import Transcriber
from .tray import TrayApp

Status = Literal["Idle", "Recording", "Transcribing", "Pasting", "Error"]
LanguageMode = Literal["auto", "en", "es"]

STATUS_IDLE: Status = "Idle"
STATUS_RECORDING: Status = "Recording"
STATUS_TRANSCRIBING: Status = "Transcribing"
STATUS_PASTING: Status = "Pasting"
STATUS_ERROR: Status = "Error"


class AppController:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.logger = get_logger(__name__)
        self.recorder = Recorder()
        self.transcriber = Transcriber(settings)
        self.tray = TrayApp(self)
        self.hotkeys = HotkeyManager(settings.hotkeys, self.on_hotkey)
        self._lock = threading.RLock()
        self._status: Status = STATUS_IDLE
        self._processing = False
        self._shutdown = False
        self._recording_language_mode: LanguageMode | None = None

    def run(self) -> None:
        self.set_status(STATUS_IDLE)
        try:
            self.hotkeys.start()
            self.logger.info("Hotkey listener started.")
        except Exception:
            self._handle_error("Hotkey listener failed to start.")

        try:
            self.tray.run()
        finally:
            self.stop()

    def stop(self) -> None:
        with self._lock:
            already_shutdown = self._shutdown
            self._shutdown = True

        if already_shutdown:
            self.tray.stop()
            return

        try:
            self.hotkeys.stop()
        except Exception:
            self.logger.exception("Hotkey listener failed to stop cleanly.")

        if self.recorder.is_recording():
            try:
                audio_path = self.recorder.stop_recording()
                self._delete_audio(audio_path)
            except Exception:
                self.logger.exception("Active recording failed to stop during shutdown.")

        self.tray.stop()
        self.logger.info("WinWhisperDictate stopped.")

    def exit_app(self) -> None:
        self.logger.info("Exit requested.")
        self.stop()

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
        with self._lock:
            if self._processing:
                self.logger.info("Ignoring toggle while dictation is being processed.")
                return

            if self.recorder.is_recording():
                language_mode = self._recording_language_mode or self.settings.language_mode
                self._processing = True
                self.logger.info("Recording stopped; transcribing (language_mode=%s).", language_mode)
                self._beep(440, 120)
                worker = threading.Thread(
                    target=self._stop_and_process,
                    args=(language_mode,),
                    name="winwhisper-dictation-worker",
                    daemon=True,
                )
                worker.start()
                return

            language_mode = language_override or self.settings.language_mode
            try:
                self.recorder.start_recording()
            except Exception:
                self._handle_error("Recording failed to start.")
                return

            self._recording_language_mode = language_mode
            self.logger.info("Recording started (language_mode=%s).", language_mode)
            self._beep(880, 120)
            self.set_status(STATUS_RECORDING)

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
        except Exception:
            self._handle_error("Settings file could not be opened.")

    def run_diagnostics(self) -> None:
        thread = threading.Thread(
            target=self._run_diagnostics_worker,
            name="winwhisper-diagnostics-worker",
            daemon=True,
        )
        thread.start()

    def notify(self, title: str, message: str) -> None:
        self.tray.notify(title, message)

    def set_status(self, status: Status) -> None:
        with self._lock:
            self._status = status
        self.tray.set_status(status)

    def is_recording(self) -> bool:
        return self.recorder.is_recording()

    def _stop_and_process(self, language_mode: LanguageMode) -> None:
        audio_path: Path | None = None
        failed = False

        try:
            audio_path = self.recorder.stop_recording()
            self.set_status(STATUS_TRANSCRIBING)
            result = self.transcriber.transcribe(audio_path, language_mode)
            self._delete_audio(audio_path)
            audio_path = None

            if not result.text.strip():
                self.notify("WinWhisperDictate", "No speech detected")
                return

            cleaned = clean_text(result.text, self.settings.cleanup_mode)
            if not cleaned.strip():
                self.notify("WinWhisperDictate", "No speech detected")
                return

            self.set_status(STATUS_PASTING)
            if not insert_text(cleaned):
                self.notify("WinWhisperDictate", "Text copied to clipboard.")
        except Exception:
            failed = True
            self._handle_error("Dictation failed.")
        finally:
            if audio_path is not None:
                self._delete_audio(audio_path)
            with self._lock:
                self._processing = False
                self._recording_language_mode = None
                shutdown = self._shutdown
            if not failed and not shutdown:
                self.set_status(STATUS_IDLE)

    def _run_diagnostics_worker(self) -> None:
        try:
            output = io.StringIO()
            with redirect_stdout(output):
                run_diagnostics_report()
            report = output.getvalue().strip()
            self.logger.info("Diagnostics report:\n%s", report or "(no output)")
            self.notify(
                "WinWhisperDictate",
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
        self.notify("WinWhisperDictate", message)

    def _beep(self, frequency: int, duration_ms: int) -> None:
        try:
            import winsound

            winsound.Beep(frequency, duration_ms)
        except Exception as exc:
            self.logger.warning("Beep failed with %s.", exc.__class__.__name__)


def main() -> int:
    logger = get_logger(__name__)
    logger.info("WinWhisperDictate starting.")
    _apply_startup_mitigations(logger)

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
        logger.exception("WinWhisperDictate exited after an unhandled error.")
        controller.stop()
        return 1
    return 0


def _apply_startup_mitigations(logger: logging.Logger) -> None:
    _drop_invalid_sslkeylogfile(logger)
    _inject_truststore(logger)


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


if __name__ == "__main__":
    raise SystemExit(main())
