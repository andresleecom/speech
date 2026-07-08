from __future__ import annotations

import tempfile
import threading
import uuid
import wave
from pathlib import Path
from typing import Any

from .logger import get_logger

SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2
DTYPE = "int16"
INT16_PEAK = 32768.0
LEVEL_DECAY = 0.72


class RecorderError(RuntimeError):
    pass


class Recorder:
    def __init__(self) -> None:
        self._stream: Any | None = None
        self._blocks: list[Any] = []
        self._lock = threading.Lock()
        self._logger = get_logger(__name__)
        self._level = 0.0

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

        def callback(indata: Any, frames: int, time: Any, status: Any) -> None:
            if status:
                self._logger.warning("Audio input status: %s", status)
            self._record_block(indata)

        try:
            stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                callback=callback,
            )
            stream.start()
        except Exception as exc:
            with self._lock:
                self._blocks = []
            raise RecorderError(
                f"Could not start microphone recording: {exc.__class__.__name__}."
            ) from exc

        self._stream = stream

    def stop_recording(self) -> Path:
        stream = self._stream
        if stream is None:
            raise RecorderError("No active recording to stop.")

        self._stream = None
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

        if blocks:
            audio = np.concatenate(blocks, axis=0)
        else:
            audio = np.empty((0, CHANNELS), dtype=DTYPE)

        output_dir = Path(tempfile.gettempdir()) / "WinWhisperDictate"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"rec-{uuid.uuid4().hex}.wav"

        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(CHANNELS)
            wav_file.setsampwidth(SAMPLE_WIDTH_BYTES)
            wav_file.setframerate(SAMPLE_RATE)
            wav_file.writeframes(audio.astype(DTYPE, copy=False).tobytes())

        return output_path

    def is_recording(self) -> bool:
        return self._stream is not None

    def current_level(self) -> float:
        with self._lock:
            return self._level

    def _record_block(self, indata: Any) -> None:
        block = indata.copy()
        level = _audio_level_from_block(block)
        with self._lock:
            self._blocks.append(block)
            self._level = _smooth_audio_level(self._level, level)


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
