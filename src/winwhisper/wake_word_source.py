"""sounddevice-based wake-word audio source for Windows and Linux."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from .audio_inputs import normalize_audio_input_device
from .logger import get_logger
from .recorder import CHANNELS, DTYPE, SAMPLE_RATE, RecorderError


class SounddeviceSource:
    """Continuously captures microphone blocks and forwards them onward.

    Implements the ``AudioSource`` protocol from ``wake_word.py``. The stream
    is opened on ``start`` and closed on ``stop`` so the microphone is fully
    released while a dictation recording owns it.
    """

    def __init__(self, audio_input_device: int | None = None) -> None:
        self._audio_input_device = normalize_audio_input_device(audio_input_device)
        self._stream: Any | None = None
        self._lock = threading.Lock()
        self._logger = get_logger(__name__)

    def start(self, on_block: Callable[[Any], None]) -> None:
        with self._lock:
            if self._stream is not None:
                return
            audio_input_device = self._audio_input_device

        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RecorderError(
                "sounddevice is not installed; wake-word listening is unavailable."
            ) from exc

        def callback(indata: Any, frames: int, time: Any, status: Any) -> None:
            if status:
                self._logger.warning("Wake-word audio input status: %s", status)
            on_block(indata)

        options: dict[str, Any] = {
            "samplerate": SAMPLE_RATE,
            "channels": CHANNELS,
            "dtype": DTYPE,
            "callback": callback,
        }
        if audio_input_device is not None:
            options["device"] = audio_input_device

        stream: Any | None = None
        try:
            stream = sd.InputStream(**options)
            stream.start()
        except Exception as exc:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            raise RecorderError(
                "Could not start wake-word microphone listening "
                f"({exc.__class__.__name__}). Check microphone permissions."
            ) from exc

        with self._lock:
            self._stream = stream

    def stop(self) -> None:
        with self._lock:
            stream = self._stream
            self._stream = None
        if stream is None:
            return
        try:
            stream.abort(ignore_errors=True)
        except Exception:
            pass
        try:
            stream.close(ignore_errors=True)
        except Exception:
            self._logger.exception("Could not close wake-word microphone stream.")

    def is_running(self) -> bool:
        with self._lock:
            return self._stream is not None
