from __future__ import annotations

import tempfile
import threading
import time
import uuid
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .audio_inputs import (
    ResolvedInputDevice,
    input_stream_extra_settings,
    list_audio_input_devices,
    normalize_audio_input_device,
    resolve_input_device,
)
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
FIRST_BLOCK_WARN_SECONDS = 0.5


class RecorderError(RuntimeError):
    def __init__(self, message: str, details: str = "") -> None:
        super().__init__(message)
        self.details = details


@dataclass(frozen=True, slots=True)
class TakeStats:
    frames: int
    peak: float
    seconds: float
    first_block_ms: float | None
    device_label: str


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
        self._peak_level = 0.0
        self._sample_count = 0
        self._max_samples = max(1, max_samples)
        self._max_duration_reached = False
        self._on_max_duration = on_max_duration
        self._audio_input_device = normalize_audio_input_device(audio_input_device)
        self._audio_input_device_name: str | None = None
        self._audio_input_device_host_api: str | None = None
        self.last_resolution: ResolvedInputDevice | None = None
        self._stream_started_at: float | None = None
        self._first_block_at: float | None = None
        self._first_block_timer: threading.Timer | None = None
        self._first_block_warned = False
        self._device_label = "System Default"
        self._last_take_stats: TakeStats | None = None
        self._last_to_stream_ms = 0

    def start_recording(self) -> None:
        if self.is_recording():
            return

        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RecorderError(
                "sounddevice is not installed; microphone recording is unavailable."
            ) from exc

        self._cancel_first_block_timer()
        open_started = time.perf_counter()
        with self._lock:
            self._blocks = []
            self._level = 0.0
            self._peak_level = 0.0
            self._sample_count = 0
            self._max_duration_reached = False
            self._stream_started_at = None
            self._first_block_at = None
            self._first_block_warned = False
            name = self._audio_input_device_name
            host_api = self._audio_input_device_host_api
            index_hint = self._audio_input_device

        devices = list_audio_input_devices()
        resolved = resolve_input_device(name, host_api, index_hint, devices)
        self.last_resolution = resolved
        self._device_label = resolved.label
        extras = _extras_for_resolved_index(resolved.index, devices)

        def callback(indata: Any, frames: int, time_info: Any, status: Any) -> None:
            if status:
                self._logger.warning("Audio input status: %s", status)
            self._record_block(indata)

        stream: Any | None = None
        try:
            stream = _input_stream(sd, callback, resolved.index, extras)
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
                self._peak_level = 0.0
            message = "Could not start microphone recording"
            if resolved.index is not None or name is not None:
                message += (
                    ". The selected microphone may be unavailable. Open the "
                    "Microphone menu and choose System Default or another device"
                )
            else:
                message += (
                    ". Check microphone permissions or choose another device in "
                    "the Microphone menu"
                )
            raise RecorderError(
                f"{message} ({exc.__class__.__name__}).",
                details=(
                    f"{exc.__class__.__name__}: {exc}; "
                    f"device={resolved.index}; label={resolved.label}"
                ),
            ) from exc

        stream_started = time.perf_counter()
        to_stream_ms = int((stream_started - open_started) * 1000)
        with self._lock:
            self._stream = stream
            self._stream_started_at = stream_started
            self._last_to_stream_ms = to_stream_ms

        timer = threading.Timer(
            FIRST_BLOCK_WARN_SECONDS,
            self._warn_if_no_first_block,
        )
        timer.daemon = True
        with self._lock:
            self._first_block_timer = timer
        timer.start()

    def stop_recording(self) -> Path | None:
        with self._lock:
            stream = self._stream
            self._stream = None

        if stream is None:
            # Idempotent: concurrent stop (worker + shutdown) is non-fatal.
            return None

        self._cancel_first_block_timer()

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

        stopped_at = time.perf_counter()
        with self._lock:
            blocks = self._blocks
            frames = self._sample_count
            peak = self._peak_level
            stream_started = self._stream_started_at
            first_block = self._first_block_at
            device_label = self._device_label
            self._blocks = []
            self._level = 0.0
            self._peak_level = 0.0
            self._sample_count = 0
            self._stream_started_at = None
            self._first_block_at = None

        seconds = (
            max(0.0, stopped_at - stream_started)
            if stream_started is not None
            else 0.0
        )
        first_block_ms: float | None = None
        if first_block is not None and stream_started is not None:
            first_block_ms = (first_block - stream_started) * 1000.0
        elif stream_started is not None and seconds >= FIRST_BLOCK_WARN_SECONDS:
            self._warn_if_no_first_block()

        self._last_take_stats = TakeStats(
            frames=frames,
            peak=peak,
            seconds=seconds,
            first_block_ms=first_block_ms,
            device_label=device_label,
        )

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

    def last_take_stats(self) -> TakeStats | None:
        return self._last_take_stats

    def last_to_stream_ms(self) -> int:
        return self._last_to_stream_ms

    def is_recording(self) -> bool:
        with self._lock:
            return self._stream is not None

    def recent_audio(self, seconds: float) -> Any | None:
        """Copy of the most recent recorded audio as an int16 1-D array.

        Used by the stop-word monitor while a hands-free recording is active.
        Returns None when not recording or nothing has been captured yet.
        """
        try:
            import numpy as np
        except ImportError:
            return None

        wanted = max(1, int(seconds * SAMPLE_RATE))
        with self._lock:
            if self._stream is None or not self._blocks:
                return None
            tail: list[Any] = []
            remaining = wanted
            for block in reversed(self._blocks):
                if remaining <= 0:
                    break
                if block.shape[0] <= remaining:
                    tail.append(block)
                    remaining -= int(block.shape[0])
                else:
                    tail.append(block[-remaining:])
                    remaining = 0
            tail.reverse()
            return np.concatenate(tail, axis=0).reshape(-1).copy()

    def set_recent_audio_capture(self, enabled: bool) -> None:
        """No-op here: recorded blocks are always buffered for recent_audio.

        Kept for interface parity with the macOS recorder, which only buffers
        live samples when asked before start_recording.
        """

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

    def set_audio_input_selection(
        self,
        name: str | None,
        host_api: str | None,
        index_hint: object,
    ) -> None:
        selected_device = normalize_audio_input_device(index_hint)
        normalized_name = _normalize_identity_text(name)
        normalized_host_api = _normalize_identity_text(host_api)
        with self._lock:
            if self._stream is not None:
                raise RecorderError("Stop dictation before changing the microphone.")
            self._audio_input_device_name = normalized_name
            self._audio_input_device_host_api = normalized_host_api
            self._audio_input_device = selected_device

    def _record_block(self, indata: Any) -> None:
        block = indata.copy()
        level = _audio_level_from_block(block)
        notify_limit = False
        with self._lock:
            if self._first_block_at is None:
                self._first_block_at = time.perf_counter()
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
            self._peak_level = max(self._peak_level, level)

        if notify_limit and self._on_max_duration is not None:
            try:
                self._on_max_duration()
            except Exception:
                self._logger.exception("Max-duration callback failed.")

    def _warn_if_no_first_block(self) -> None:
        with self._lock:
            if self._first_block_warned or self._first_block_at is not None:
                return
            self._first_block_warned = True
            label = self._device_label
        self._logger.warning(
            "No audio blocks received within 500ms from %s",
            label,
        )

    def _cancel_first_block_timer(self) -> None:
        with self._lock:
            timer = self._first_block_timer
            self._first_block_timer = None
        if timer is not None:
            timer.cancel()


class MicrophoneTest:
    """Capture only live microphone level for a short, non-recording test."""

    def __init__(self, audio_input_device: int | None = None) -> None:
        self._audio_input_device = normalize_audio_input_device(audio_input_device)
        self._audio_input_device_name: str | None = None
        self._audio_input_device_host_api: str | None = None
        self._stream: Any | None = None
        self._lock = threading.Lock()
        self._logger = get_logger(__name__)
        self._level = 0.0
        self._peak_level = 0.0
        self.last_resolution: ResolvedInputDevice | None = None

    def start(self) -> None:
        with self._lock:
            if self._stream is not None:
                return
            self._level = 0.0
            self._peak_level = 0.0
            name = self._audio_input_device_name
            host_api = self._audio_input_device_host_api
            index_hint = self._audio_input_device

        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RecorderError(
                "sounddevice is not installed; microphone testing is unavailable."
            ) from exc

        devices = list_audio_input_devices()
        resolved = resolve_input_device(name, host_api, index_hint, devices)
        self.last_resolution = resolved
        extras = _extras_for_resolved_index(resolved.index, devices)

        def callback(indata: Any, frames: int, time: Any, status: Any) -> None:
            if status:
                self._logger.warning("Microphone test input status: %s", status)
            level = _audio_level_from_block(indata)
            with self._lock:
                self._level = _smooth_audio_level(self._level, level)
                self._peak_level = max(self._peak_level, level)

        stream: Any | None = None
        try:
            stream = _input_stream(sd, callback, resolved.index, extras)
            stream.start()
        except Exception as exc:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            message = "Could not start microphone test"
            if resolved.index is not None or name is not None:
                message += (
                    ". The selected microphone may be unavailable. Open the "
                    "Microphone menu and choose System Default or another device"
                )
            else:
                message += (
                    ". Check microphone permissions or choose another device in "
                    "the Microphone menu"
                )
            raise RecorderError(
                f"{message} ({exc.__class__.__name__}).",
                details=(
                    f"{exc.__class__.__name__}: {exc}; "
                    f"device={resolved.index}; label={resolved.label}"
                ),
            ) from exc

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

    def set_audio_input_device(self, value: object) -> None:
        selected_device = normalize_audio_input_device(value)
        with self._lock:
            if self._stream is not None:
                raise RecorderError("Stop the microphone test before changing the microphone.")
            self._audio_input_device = selected_device

    def set_audio_input_selection(
        self,
        name: str | None,
        host_api: str | None,
        index_hint: object,
    ) -> None:
        selected_device = normalize_audio_input_device(index_hint)
        normalized_name = _normalize_identity_text(name)
        normalized_host_api = _normalize_identity_text(host_api)
        with self._lock:
            if self._stream is not None:
                raise RecorderError("Stop the microphone test before changing the microphone.")
            self._audio_input_device_name = normalized_name
            self._audio_input_device_host_api = normalized_host_api
            self._audio_input_device = selected_device


def _input_stream(
    sounddevice: Any,
    callback: Callable[[Any, int, Any, Any], None],
    audio_input_device: int | None,
    extra_options: dict[str, Any] | None = None,
) -> Any:
    options: dict[str, Any] = {
        "samplerate": SAMPLE_RATE,
        "channels": CHANNELS,
        "dtype": DTYPE,
        "callback": callback,
    }
    if audio_input_device is not None:
        options["device"] = audio_input_device
    if extra_options:
        options.update(extra_options)
    return sounddevice.InputStream(**options)


def _extras_for_resolved_index(
    index: int | None,
    devices: tuple[Any, ...],
) -> dict[str, Any]:
    if index is None:
        return {}
    for device in devices:
        if getattr(device, "index", None) == index:
            return input_stream_extra_settings(getattr(device, "host_api", None))
    return {}


def _normalize_identity_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


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
