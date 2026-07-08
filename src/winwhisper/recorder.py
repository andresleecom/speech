from __future__ import annotations

import tempfile
import threading
import uuid
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

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

        def callback(indata: Any, frames: int, time: Any, status: Any) -> None:
            if status:
                self._logger.warning("Audio input status: %s", status)
            self._record_block(indata)

        stream: Any | None = None
        try:
            stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                callback=callback,
            )
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
            raise RecorderError(
                f"Could not start microphone recording: {exc.__class__.__name__}."
            ) from exc

        with self._lock:
            self._stream = stream

    def stop_recording(self) -> Path | None:
        with self._lock:
            stream = self._stream
            self._stream = None

        if stream is None:
            # Idempotent: concurrent stop (worker + shutdown) is non-fatal.
            return None

        try:
            stream.stop()
            stream.close()
        except Exception as exc:
            raise RecorderError(
                f"Could not stop microphone recording: {exc.__class__.__name__}."
            ) from exc

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
