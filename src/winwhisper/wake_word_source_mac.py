"""AVFoundation-based wake-word audio source for macOS.

Mirrors ``SounddeviceSource`` but streams sample buffers through
``AVCaptureAudioDataOutput`` instead of PortAudio, matching the app's
deliberate move to native macOS capture (see ``recorder_mac.py``).
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from .audio_inputs import (
    AudioInputDeviceError,
    macos_audio_capture_device,
    normalize_audio_input_device,
)
from .logger import get_logger
from .recorder import SAMPLE_RATE, RecorderError
from .recorder_mac import (
    _ensure_microphone_permission,
    _native_audio_frameworks,
    _native_error_suffix,
    _new_data_output_delegate,
    _new_data_output_queue,
    _objc_result,
    _wait_for_worker_event,
)


class MacAudioSource:
    """Continuously captures microphone blocks and forwards them onward.

    Implements the ``AudioSource`` protocol from ``wake_word.py``. The capture
    session is created on ``start`` and torn down on ``stop`` so the
    microphone is fully released while a dictation recording owns it.
    """

    def __init__(self, audio_input_device: int | None = None) -> None:
        self._audio_input_device = normalize_audio_input_device(audio_input_device)
        self._worker = _ListenWorker()
        self._logger = get_logger(__name__)

    def start(self, on_block: Callable[[Any], None]) -> None:
        self._worker.start(self._audio_input_device, on_block)

    def stop(self) -> None:
        self._worker.stop_capture()

    def is_running(self) -> bool:
        return self._worker.is_active()

    def close(self) -> None:
        self._worker.close()


@dataclass(slots=True)
class _ListenCommand:
    name: Literal["start", "stop", "close"]
    audio_input_device: int | None = None
    on_block: Callable[[Any], None] | None = None
    done: threading.Event = field(default_factory=threading.Event)
    error: BaseException | None = None


@dataclass(slots=True)
class _NativeListener:
    session: Any
    output: Any
    delegate: Any


class _ListenWorker:
    """Serialize every AVCaptureSession operation on one worker thread."""

    def __init__(self) -> None:
        self._commands: queue.Queue[_ListenCommand] = queue.Queue()
        self._lock = threading.Lock()
        self._logger = get_logger(__name__)
        self._native_listener: _NativeListener | None = None
        self._active = False
        self._closed = False
        self._thread = threading.Thread(
            target=self._run,
            name="winwhisper-avfoundation-listener",
            daemon=True,
        )
        self._thread.start()

    def start(
        self,
        audio_input_device: int | None,
        on_block: Callable[[Any], None],
    ) -> None:
        with self._lock:
            if self._active:
                return
        self._call(
            _ListenCommand(
                "start",
                audio_input_device=audio_input_device,
                on_block=on_block,
            )
        )

    def stop_capture(self) -> None:
        with self._lock:
            if not self._active or self._closed:
                return
        self._call(_ListenCommand("stop"))

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._call(_ListenCommand("close"), allow_closed=True)

    def is_active(self) -> bool:
        with self._lock:
            return self._active

    def _call(
        self,
        command: _ListenCommand,
        *,
        allow_closed: bool = False,
    ) -> None:
        with self._lock:
            if self._closed and not allow_closed:
                raise RecorderError("The macOS wake-word listener is closed.")
        self._commands.put(command)
        _wait_for_worker_event(command.done)
        if command.error is not None:
            raise command.error

    def _run(self) -> None:
        import objc

        while True:
            command = self._commands.get()
            with objc.autorelease_pool():
                try:
                    if command.name == "start":
                        if command.on_block is None:
                            raise RecorderError("No audio block callback was provided.")
                        self._start_native_listener(
                            command.audio_input_device,
                            command.on_block,
                        )
                    elif command.name == "stop":
                        self._stop_native_listener()
                    else:
                        self._stop_native_listener()
                except BaseException as exc:
                    command.error = exc
                finally:
                    command.done.set()

            if command.name == "close":
                return

    def _start_native_listener(
        self,
        audio_input_device: int | None,
        on_block: Callable[[Any], None],
    ) -> None:
        avfoundation, _nsurl, linear_pcm = _native_audio_frameworks()
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
            output = avfoundation.AVCaptureAudioDataOutput.alloc().init()
            delegate = _new_data_output_delegate(on_block)
            session.beginConfiguration()
            try:
                if not session.canAddInput_(device_input):
                    raise RecorderError(
                        "macOS could not attach the selected microphone to the "
                        "wake-word capture session."
                    )
                session.addInput_(device_input)
                if not session.canAddOutput_(output):
                    raise RecorderError(
                        "macOS could not create a streaming audio capture output."
                    )
                session.addOutput_(output)
                # Ask for the house format directly; the sample conversion in
                # recorder_mac still handles devices that ignore this.
                output.setAudioSettings_(
                    {
                        avfoundation.AVFormatIDKey: linear_pcm,
                        avfoundation.AVSampleRateKey: float(SAMPLE_RATE),
                        avfoundation.AVNumberOfChannelsKey: 1,
                        avfoundation.AVLinearPCMBitDepthKey: 16,
                        avfoundation.AVLinearPCMIsFloatKey: False,
                        avfoundation.AVLinearPCMIsBigEndianKey: False,
                    }
                )
                output.setSampleBufferDelegate_queue_(
                    delegate,
                    _new_data_output_queue(),
                )
            finally:
                session.commitConfiguration()

            session.startRunning()
            if not session.isRunning():
                raise RecorderError(
                    "macOS could not start the wake-word capture session."
                )
        except Exception as exc:
            if session is not None:
                try:
                    if session.isRunning():
                        session.stopRunning()
                except Exception:
                    pass
            if isinstance(exc, RecorderError):
                raise
            raise RecorderError(
                "Could not start wake-word microphone listening "
                f"({exc.__class__.__name__}). Check microphone permission and "
                "the selected input."
            ) from exc

        self._native_listener = _NativeListener(
            session=session,
            output=output,
            delegate=delegate,
        )
        with self._lock:
            self._active = True

    def _stop_native_listener(self) -> None:
        listener = self._native_listener
        self._native_listener = None
        with self._lock:
            self._active = False
        if listener is None:
            return
        try:
            if listener.session.isRunning():
                listener.session.stopRunning()
        except Exception:
            self._logger.exception("Could not stop the wake-word capture session.")
