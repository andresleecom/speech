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


class RecorderError(RuntimeError):
    pass


class Recorder:
    def __init__(self) -> None:
        self._stream: Any | None = None
        self._blocks: list[Any] = []
        self._lock = threading.Lock()
        self._logger = get_logger(__name__)

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

        def callback(indata: Any, frames: int, time: Any, status: Any) -> None:
            if status:
                self._logger.warning("Audio input status: %s", status)
            with self._lock:
                self._blocks.append(indata.copy())

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
