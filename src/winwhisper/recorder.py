from __future__ import annotations

import tempfile
import threading
import uuid
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .audio_inputs import normalize_audio_input_device
from .branding import APP_NAME
from .logger import get_logger

SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2
DTYPE = "int16"
INT16_PEAK = 32768.0
LEVEL_DECAY = 0.72
# Cap recording length so a forgotten take cannot OOM the process.
MAX_RECORDING_SECONDS = 10 * 60
MAX_RECORDING_SAMPLES = SAMPLE_RATE * MAX_RECORDING_SECONDS


class RecorderError(RuntimeError):
    pass


class Recorder:
    def __init__(
        self,
        max_samples: int = MAX_RECORDING_SAMPLES,
        on_max_duration: Callable[[], None] | None = None,
        audio_input_device: int | None = None,
    ) -> None:
        self._stream: Any | None = None
        self._blocks: list[Any] = []
        self._lock = threading.Lock()
        self._logger = get_logger(__name__)
        self._level = 0.0
        self._sample_count = 0
        self._max_samples = max(1, max_samples)
        self._max_duration_reached = False
        self._on_max_duration = on_max_duration
        self._audio_input_device = normalize_audio_input_device(audio_input_device)

    def start_recording(self) -> None:
        if self.is_recording():
            return

        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RecorderError(
                "sounddevice is not installed; microphone recording is unavailable."
            ) from exc

        with self._lock:
            self._blocks = []
            self._level = 0.0
            self._sample_count = 0
            self._max_duration_reached = False
            audio_input_device = self._audio_input_device

        def callback(indata: Any, frames: int, time: Any, status: Any) -> None:
            if status:
                self._logger.warning("Audio input status: %s", status)
            self._record_block(indata)

        stream: Any | None = None
        try:
            stream = _input_stream(sd, callback, audio_input_device)
            stream.start()
        except Exception as exc:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            with self._lock:
                self._blocks = []
                self._sample_count = 0
            message = "Could not start microphone recording"
            if audio_input_device is not None:
                message += (
                    ". The selected microphone may be unavailable. Open the "
                    "Microphone menu and choose System Default or another device"
                )
            else:
                message += (
                    ". Check microphone permissions or choose another device in "
                    "the Microphone menu"
                )
            raise RecorderError(f"{message} ({exc.__class__.__name__}).") from exc

        with self._lock:
            self._stream = stream

    def stop_recording(self) -> Path | None:
        with self._lock:
            stream = self._stream
            self._stream = None

        if stream is None:
            # Idempotent: concurrent stop (worker + shutdown) is non-fatal.
            return None

        abort_error: Exception | None = None
        close_error: Exception | None = None
        try:
            stream.abort(ignore_errors=False)
        except Exception as exc:
            abort_error = exc
        finally:
            try:
                stream.close(ignore_errors=True)
            except Exception as exc:
                close_error = exc

        if abort_error is not None:
            raise RecorderError(
                "Could not stop microphone recording: "
                f"{abort_error.__class__.__name__}."
            ) from abort_error
        if close_error is not None:
            raise RecorderError(
                "Could not close microphone recording: "
                f"{close_error.__class__.__name__}."
            ) from close_error

        try:
            import numpy as np
        except ImportError as exc:
            raise RecorderError("numpy is not installed; cannot write recording.") from exc

        with self._lock:
            blocks = self._blocks
            self._blocks = []
            self._level = 0.0
            self._sample_count = 0

        if blocks:
            audio = np.concatenate(blocks, axis=0)
        else:
            audio = np.empty((0, CHANNELS), dtype=DTYPE)

        output_dir = Path(tempfile.gettempdir()) / APP_NAME
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"rec-{uuid.uuid4().hex}.wav"

        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(CHANNELS)
            wav_file.setsampwidth(SAMPLE_WIDTH_BYTES)
            wav_file.setframerate(SAMPLE_RATE)
            wav_file.writeframes(audio.astype(DTYPE, copy=False).tobytes())

        return output_path

    def is_recording(self) -> bool:
        with self._lock:
            return self._stream is not None

    def max_duration_reached(self) -> bool:
        with self._lock:
            return self._max_duration_reached

    def current_level(self) -> float:
        with self._lock:
            return self._level

    def audio_input_device(self) -> int | None:
        with self._lock:
            return self._audio_input_device

    def set_audio_input_device(self, value: object) -> None:
        selected_device = normalize_audio_input_device(value)
        with self._lock:
            if self._stream is not None:
                raise RecorderError("Stop dictation before changing the microphone.")
            self._audio_input_device = selected_device

    def _record_block(self, indata: Any) -> None:
        block = indata.copy()
        level = _audio_level_from_block(block)
        notify_limit = False
        with self._lock:
            if self._sample_count >= self._max_samples:
                if not self._max_duration_reached:
                    self._max_duration_reached = True
                    notify_limit = True
                return

            remaining = self._max_samples - self._sample_count
            if block.shape[0] > remaining:
                block = block[:remaining]
                self._max_duration_reached = True
                notify_limit = True

            self._blocks.append(block)
            self._sample_count += int(block.shape[0])
            self._level = _smooth_audio_level(self._level, level)

        if notify_limit and self._on_max_duration is not None:
            try:
                self._on_max_duration()
            except Exception:
                self._logger.exception("Max-duration callback failed.")


class MicrophoneTest:
    """Capture only live microphone level for a short, non-recording test."""

    def __init__(self, audio_input_device: int | None = None) -> None:
        self._audio_input_device = normalize_audio_input_device(audio_input_device)
        self._stream: Any | None = None
        self._lock = threading.Lock()
        self._logger = get_logger(__name__)
        self._level = 0.0
        self._peak_level = 0.0

    def start(self) -> None:
        with self._lock:
            if self._stream is not None:
                return
            self._level = 0.0
            self._peak_level = 0.0

        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RecorderError(
                "sounddevice is not installed; microphone testing is unavailable."
            ) from exc

        def callback(indata: Any, frames: int, time: Any, status: Any) -> None:
            if status:
                self._logger.warning("Microphone test input status: %s", status)
            level = _audio_level_from_block(indata)
            with self._lock:
                self._level = _smooth_audio_level(self._level, level)
                self._peak_level = max(self._peak_level, level)

        stream: Any | None = None
        try:
            stream = _input_stream(sd, callback, self._audio_input_device)
            stream.start()
        except Exception as exc:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            message = "Could not start microphone test"
            if self._audio_input_device is not None:
                message += (
                    ". The selected microphone may be unavailable. Open the "
                    "Microphone menu and choose System Default or another device"
                )
            else:
                message += (
                    ". Check microphone permissions or choose another device in "
                    "the Microphone menu"
                )
            raise RecorderError(f"{message} ({exc.__class__.__name__}).") from exc

        with self._lock:
            self._stream = stream

    def stop(self) -> float:
        with self._lock:
            stream = self._stream
            self._stream = None
            peak_level = self._peak_level
            self._level = 0.0

        if stream is None:
            return peak_level
        abort_error: Exception | None = None
        close_error: Exception | None = None
        try:
            stream.abort(ignore_errors=False)
        except Exception as exc:
            abort_error = exc
        finally:
            try:
                stream.close(ignore_errors=True)
            except Exception as exc:
                close_error = exc

        if abort_error is not None:
            raise RecorderError(
                f"Could not stop microphone test: {abort_error.__class__.__name__}."
            ) from abort_error
        if close_error is not None:
            raise RecorderError(
                f"Could not close microphone test: {close_error.__class__.__name__}."
            ) from close_error
        return peak_level

    def is_running(self) -> bool:
        with self._lock:
            return self._stream is not None

    def current_level(self) -> float:
        with self._lock:
            return self._level


def _input_stream(
    sounddevice: Any,
    callback: Callable[[Any, int, Any, Any], None],
    audio_input_device: int | None,
) -> Any:
    options: dict[str, Any] = {
        "samplerate": SAMPLE_RATE,
        "channels": CHANNELS,
        "dtype": DTYPE,
        "callback": callback,
    }
    if audio_input_device is not None:
        options["device"] = audio_input_device
    return sounddevice.InputStream(**options)


def _audio_level_from_block(block: Any) -> float:
    try:
        import numpy as np

        samples = np.asarray(block, dtype="float32")
        if samples.size == 0:
            return 0.0

        rms = float(np.sqrt(np.mean(np.square(samples))))
        if rms > 1.0:
            rms /= INT16_PEAK
        return min(1.0, max(0.0, rms))
    except Exception:
        return 0.0


def _smooth_audio_level(current_level: float, incoming_level: float) -> float:
    if incoming_level >= current_level:
        return incoming_level
    return max(0.0, current_level * LEVEL_DECAY + incoming_level * (1.0 - LEVEL_DECAY))
