from __future__ import annotations

import math
import queue
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .audio_inputs import (
    AudioInputDeviceError,
    macos_audio_capture_device,
    normalize_audio_input_device,
)
from .branding import APP_NAME
from .logger import get_logger
from .recorder import (
    MAX_RECORDING_SAMPLES,
    SAMPLE_RATE,
    RecorderError,
    _smooth_audio_level,
)

NATIVE_SAMPLE_RATE = 48_000.0
METER_POLL_SECONDS = 0.05
METER_FLOOR_DB = -80.0
RECORDING_START_TIMEOUT_SECONDS = 3.0
RECORDING_FINALIZE_TIMEOUT_SECONDS = 3.0
MICROPHONE_PERMISSION_TIMEOUT_SECONDS = 60.0


class Recorder:
    """macOS recorder backed by AVFoundation instead of PortAudio."""

    def __init__(
        self,
        max_samples: int = MAX_RECORDING_SAMPLES,
        on_max_duration: Callable[[], None] | None = None,
        audio_input_device: int | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._audio_input_device = normalize_audio_input_device(audio_input_device)
        self._capture = _CaptureWorker(
            max_duration_seconds=max(1, max_samples) / SAMPLE_RATE,
            on_max_duration=on_max_duration,
        )

    def start_recording(self) -> None:
        if self.is_recording():
            return
        with self._lock:
            selected_device = self._audio_input_device
        self._capture.start(_new_output_path("rec"), selected_device)

    def stop_recording(self) -> Path | None:
        return self._capture.stop()

    def is_recording(self) -> bool:
        return self._capture.is_active()

    def max_duration_reached(self) -> bool:
        return self._capture.max_duration_reached()

    def current_level(self) -> float:
        return self._capture.current_level()

    def audio_input_device(self) -> int | None:
        with self._lock:
            return self._audio_input_device

    def set_audio_input_device(self, value: object) -> None:
        selected_device = normalize_audio_input_device(value)
        if self.is_recording():
            raise RecorderError("Stop dictation before changing the microphone.")
        try:
            macos_audio_capture_device(selected_device)
        except AudioInputDeviceError as exc:
            raise RecorderError(str(exc)) from exc
        with self._lock:
            self._audio_input_device = selected_device


class MicrophoneTest:
    """Measure live macOS microphone levels, deleting its temporary audio file."""

    def __init__(self, audio_input_device: int | None = None) -> None:
        self._audio_input_device = normalize_audio_input_device(audio_input_device)
        self._capture = _CaptureWorker()
        self._output_path: Path | None = None

    def start(self) -> None:
        if self.is_running():
            return
        output_path = _new_output_path("mic-test")
        try:
            self._capture.start(output_path, self._audio_input_device)
        except Exception:
            output_path.unlink(missing_ok=True)
            self._capture.close()
            raise
        self._output_path = output_path

    def stop(self) -> float:
        peak_level = self._capture.peak_level()
        output_path = self._output_path
        self._output_path = None
        try:
            recorded_path = self._capture.stop()
            peak_level = max(peak_level, self._capture.peak_level())
        finally:
            self._capture.close()
            if output_path is not None:
                output_path.unlink(missing_ok=True)
        if recorded_path is not None:
            recorded_path.unlink(missing_ok=True)
        return peak_level

    def is_running(self) -> bool:
        return self._capture.is_active()

    def current_level(self) -> float:
        return self._capture.current_level()


@dataclass(slots=True)
class _CaptureCommand:
    name: Literal["start", "stop", "close"]
    output_path: Path | None = None
    audio_input_device: int | None = None
    done: threading.Event = field(default_factory=threading.Event)
    result: Path | None = None
    error: BaseException | None = None


@dataclass(slots=True)
class _NativeCapture:
    session: Any
    output: Any
    delegate: Any
    output_path: Path


class _CaptureWorker:
    """Serialize every AVCaptureSession operation on one worker thread."""

    def __init__(
        self,
        *,
        max_duration_seconds: float | None = None,
        on_max_duration: Callable[[], None] | None = None,
    ) -> None:
        self._commands: queue.Queue[_CaptureCommand] = queue.Queue()
        self._lock = threading.Lock()
        self._logger = get_logger(__name__)
        self._native_capture: _NativeCapture | None = None
        self._active = False
        self._closed = False
        self._level = 0.0
        self._peak_level = 0.0
        self._started_at = 0.0
        self._max_duration_seconds = max_duration_seconds
        self._max_duration_was_reached = False
        self._on_max_duration = on_max_duration
        self._meter_warning_logged = False
        self._thread = threading.Thread(
            target=self._run,
            name="winwhisper-avfoundation-capture",
            daemon=True,
        )
        self._thread.start()

    def start(self, output_path: Path, audio_input_device: int | None) -> None:
        with self._lock:
            if self._active:
                return
            if self._closed:
                raise RecorderError("The macOS microphone capture worker is closed.")
        self._call(
            _CaptureCommand(
                "start",
                output_path=output_path,
                audio_input_device=audio_input_device,
            )
        )

    def stop(self) -> Path | None:
        with self._lock:
            if not self._active:
                return None
        return self._call(_CaptureCommand("stop"))

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._call(_CaptureCommand("close"), allow_closed=True)

    def is_active(self) -> bool:
        with self._lock:
            return self._active

    def current_level(self) -> float:
        with self._lock:
            return self._level

    def peak_level(self) -> float:
        with self._lock:
            return self._peak_level

    def max_duration_reached(self) -> bool:
        with self._lock:
            return self._max_duration_was_reached

    def _call(
        self,
        command: _CaptureCommand,
        *,
        allow_closed: bool = False,
    ) -> Path | None:
        with self._lock:
            if self._closed and not allow_closed:
                raise RecorderError("The macOS microphone capture worker is closed.")
        self._commands.put(command)
        _wait_for_worker_event(command.done)
        if command.error is not None:
            raise command.error
        return command.result

    def _run(self) -> None:
        import objc

        while True:
            try:
                command = self._commands.get(timeout=METER_POLL_SECONDS)
            except queue.Empty:
                with objc.autorelease_pool():
                    self._poll_capture()
                continue

            with objc.autorelease_pool():
                try:
                    if command.name == "start":
                        if command.output_path is None:
                            raise RecorderError("No recording output path was provided.")
                        self._start_native_capture(
                            command.output_path,
                            command.audio_input_device,
                        )
                    elif command.name == "stop":
                        command.result = self._stop_native_capture()
                    else:
                        if self.is_active():
                            self._stop_native_capture()
                except BaseException as exc:
                    command.error = exc
                finally:
                    command.done.set()

            if command.name == "close":
                return

    def _start_native_capture(
        self,
        output_path: Path,
        audio_input_device: int | None,
    ) -> None:
        avfoundation, nsurl, linear_pcm = _native_audio_frameworks()
        _ensure_microphone_permission(avfoundation)

        try:
            device = macos_audio_capture_device(audio_input_device)
        except AudioInputDeviceError as exc:
            raise RecorderError(str(exc)) from exc

        session: Any | None = None
        output: Any | None = None
        try:
            device_input, input_error = _objc_result(
                avfoundation.AVCaptureDeviceInput.deviceInputWithDevice_error_(
                    device,
                    None,
                )
            )
            if device_input is None:
                raise RecorderError(
                    "Could not open the selected microphone"
                    + _native_error_suffix(input_error)
                    + "."
                )

            session = avfoundation.AVCaptureSession.alloc().init()
            output = avfoundation.AVCaptureAudioFileOutput.alloc().init()
            session.beginConfiguration()
            try:
                if not session.canAddInput_(device_input):
                    raise RecorderError(
                        "macOS could not attach the selected microphone to the "
                        "capture session."
                    )
                session.addInput_(device_input)
                if not session.canAddOutput_(output):
                    raise RecorderError(
                        "macOS could not create an audio-file capture output."
                    )
                session.addOutput_(output)
                output.setAudioSettings_(
                    {
                        avfoundation.AVFormatIDKey: linear_pcm,
                        avfoundation.AVSampleRateKey: NATIVE_SAMPLE_RATE,
                        avfoundation.AVNumberOfChannelsKey: 1,
                        avfoundation.AVLinearPCMBitDepthKey: 16,
                        avfoundation.AVLinearPCMIsFloatKey: False,
                        avfoundation.AVLinearPCMIsBigEndianKey: False,
                    }
                )
            finally:
                session.commitConfiguration()

            available_types = tuple(
                avfoundation.AVCaptureAudioFileOutput.availableOutputFileTypes()
            )
            if avfoundation.AVFileTypeWAVE not in available_types:
                raise RecorderError("macOS does not offer WAV output for this microphone.")

            delegate = _new_recording_delegate()
            output_url = nsurl.fileURLWithPath_(str(output_path))
            session.startRunning()
            if not session.isRunning():
                raise RecorderError(
                    "macOS could not start the microphone capture session."
                )

            output.startRecordingToOutputFileURL_outputFileType_recordingDelegate_(
                output_url,
                avfoundation.AVFileTypeWAVE,
                delegate,
            )
            _wait_until_recording_starts(output, delegate)
        except Exception as exc:
            _stop_failed_native_capture(session, output, output_path)
            if isinstance(exc, RecorderError):
                raise
            raise RecorderError(
                "Could not start native macOS microphone recording "
                f"({exc.__class__.__name__}). Check microphone permission and "
                "the selected input."
            ) from exc

        self._native_capture = _NativeCapture(
            session=session,
            output=output,
            delegate=delegate,
            output_path=output_path,
        )
        with self._lock:
            self._active = True
            self._level = 0.0
            self._peak_level = 0.0
            self._started_at = time.monotonic()
            self._max_duration_was_reached = False
            self._meter_warning_logged = False

    def _stop_native_capture(self) -> Path | None:
        capture = self._native_capture
        if capture is None:
            with self._lock:
                self._active = False
                self._level = 0.0
            return None

        stop_error: BaseException | None = None
        try:
            if capture.output.isRecording():
                capture.output.stopRecording()
            if not capture.delegate.finished_event.wait(
                RECORDING_FINALIZE_TIMEOUT_SECONDS
            ):
                raise RecorderError(
                    "macOS did not finish writing the recording within "
                    f"{RECORDING_FINALIZE_TIMEOUT_SECONDS:.0f}s."
                )
            native_error = capture.delegate.error
            if native_error is not None:
                raise RecorderError(
                    "macOS could not finish the recording"
                    + _native_error_suffix(native_error)
                    + "."
                )
        except BaseException as exc:
            stop_error = exc
        finally:
            try:
                if capture.session.isRunning():
                    capture.session.stopRunning()
            except BaseException as exc:
                if stop_error is None:
                    stop_error = RecorderError(
                        "macOS could not stop the microphone capture session "
                        f"({exc.__class__.__name__})."
                    )
            self._native_capture = None
            with self._lock:
                self._active = False
                self._level = 0.0

        if stop_error is not None:
            capture.output_path.unlink(missing_ok=True)
            raise stop_error
        if not capture.output_path.exists():
            raise RecorderError("macOS finished recording without creating an audio file.")
        return capture.output_path

    def _poll_capture(self) -> None:
        capture = self._native_capture
        if capture is None or not self.is_active():
            return

        try:
            incoming_level = 0.0
            for connection in capture.output.connections():
                for channel in connection.audioChannels():
                    incoming_level = max(
                        incoming_level,
                        _level_from_decibels(float(channel.averagePowerLevel())),
                    )
            with self._lock:
                self._level = _smooth_audio_level(self._level, incoming_level)
                self._peak_level = max(self._peak_level, incoming_level)
        except Exception:
            with self._lock:
                already_logged = self._meter_warning_logged
                self._meter_warning_logged = True
            if not already_logged:
                self._logger.exception("Could not read AVFoundation microphone level.")

        callback: Callable[[], None] | None = None
        with self._lock:
            if (
                self._max_duration_seconds is not None
                and not self._max_duration_was_reached
                and time.monotonic() - self._started_at
                >= self._max_duration_seconds
            ):
                self._max_duration_was_reached = True
                callback = self._on_max_duration
        if callback is not None:
            try:
                callback()
            except Exception:
                self._logger.exception("Max-duration callback failed.")


_RECORDING_DELEGATE_CLASS: Any | None = None


def _new_recording_delegate() -> Any:
    delegate = _recording_delegate_class().alloc().init()
    delegate.finished_event = threading.Event()
    delegate.error = None
    return delegate


def _recording_delegate_class() -> Any:
    global _RECORDING_DELEGATE_CLASS
    if _RECORDING_DELEGATE_CLASS is not None:
        return _RECORDING_DELEGATE_CLASS

    # Importing AVFoundation registers its Objective-C protocols with PyObjC.
    import AVFoundation  # noqa: F401
    import objc
    from Foundation import NSObject

    protocol = objc.protocolNamed("AVCaptureFileOutputRecordingDelegate")

    class _SpeechAudioRecordingDelegate(NSObject, protocols=[protocol]):
        def captureOutput_didFinishRecordingToOutputFileAtURL_fromConnections_error_(
            self,
            output,
            output_file_url,
            connections,
            error,
        ) -> None:
            self.error = error
            self.finished_event.set()

    _RECORDING_DELEGATE_CLASS = _SpeechAudioRecordingDelegate
    return _RECORDING_DELEGATE_CLASS


def _native_audio_frameworks() -> tuple[Any, Any, int]:
    try:
        import AVFoundation
        from CoreAudio import kAudioFormatLinearPCM
        from Foundation import NSURL
    except ImportError as exc:
        raise RecorderError(
            "AVFoundation support is not installed; macOS microphone recording "
            "is unavailable."
        ) from exc
    return AVFoundation, NSURL, kAudioFormatLinearPCM


def _ensure_microphone_permission(avfoundation: Any) -> None:
    status = avfoundation.AVCaptureDevice.authorizationStatusForMediaType_(
        avfoundation.AVMediaTypeAudio
    )
    if status == avfoundation.AVAuthorizationStatusAuthorized:
        return
    if status in {
        avfoundation.AVAuthorizationStatusDenied,
        avfoundation.AVAuthorizationStatusRestricted,
    }:
        raise RecorderError(
            "Microphone access is disabled. Enable Speech in System Settings > "
            "Privacy & Security > Microphone, then relaunch."
        )

    completed = threading.Event()
    granted = False

    def permission_result(allowed: bool) -> None:
        nonlocal granted
        granted = bool(allowed)
        completed.set()

    avfoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
        avfoundation.AVMediaTypeAudio,
        permission_result,
    )
    if not completed.wait(MICROPHONE_PERMISSION_TIMEOUT_SECONDS):
        raise RecorderError("macOS did not finish the microphone permission request.")
    if not granted:
        raise RecorderError(
            "Microphone access was denied. Enable Speech in System Settings > "
            "Privacy & Security > Microphone, then relaunch."
        )


def _wait_until_recording_starts(output: Any, delegate: Any) -> None:
    deadline = time.monotonic() + RECORDING_START_TIMEOUT_SECONDS
    while not output.isRecording():
        if delegate.finished_event.is_set():
            raise RecorderError(
                "macOS rejected the recording request"
                + _native_error_suffix(delegate.error)
                + "."
            )
        if time.monotonic() >= deadline:
            raise RecorderError(
                "macOS did not start writing the recording within "
                f"{RECORDING_START_TIMEOUT_SECONDS:.0f}s."
            )
        time.sleep(0.01)


def _wait_for_worker_event(event: threading.Event) -> None:
    """Keep Cocoa callbacks moving when capture is called from the main thread."""
    from Foundation import NSDate, NSRunLoop, NSThread

    if not NSThread.isMainThread():
        event.wait()
        return

    run_loop = NSRunLoop.currentRunLoop()
    while not event.is_set():
        run_loop.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))


def _stop_failed_native_capture(
    session: Any | None,
    output: Any | None,
    output_path: Path,
) -> None:
    try:
        if output is not None and output.isRecording():
            output.stopRecording()
    except Exception:
        pass
    try:
        if session is not None and session.isRunning():
            session.stopRunning()
    except Exception:
        pass
    output_path.unlink(missing_ok=True)


def _objc_result(result: Any) -> tuple[Any | None, Any | None]:
    if isinstance(result, tuple):
        value = result[0] if result else None
        error = result[1] if len(result) > 1 else None
        return value, error
    return result, None


def _native_error_suffix(error: Any | None) -> str:
    if error is None:
        return ""
    try:
        description = str(error.localizedDescription()).strip()
    except Exception:
        description = ""
    return f": {description}" if description else f" ({error.__class__.__name__})"


def _level_from_decibels(value: float) -> float:
    if not math.isfinite(value) or value <= METER_FLOOR_DB:
        return 0.0
    return min(1.0, max(0.0, math.pow(10.0, value / 20.0)))


def _new_output_path(prefix: str) -> Path:
    output_dir = Path(tempfile.gettempdir()) / APP_NAME
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"{prefix}-{uuid.uuid4().hex}.wav"
