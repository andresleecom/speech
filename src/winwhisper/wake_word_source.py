"""sounddevice-based wake-word audio source for Windows and Linux."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from .audio_inputs import (
    ResolvedInputDevice,
    input_stream_extra_settings,
    list_audio_input_devices,
    normalize_audio_input_device,
    resolve_input_device,
)
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
        self._audio_input_device_name: str | None = None
        self._audio_input_device_host_api: str | None = None
        self._stream: Any | None = None
        self._lock = threading.Lock()
        self._logger = get_logger(__name__)
        self.last_resolution: ResolvedInputDevice | None = None

    def start(self, on_block: Callable[[Any], None]) -> None:
        with self._lock:
            if self._stream is not None:
                return
            name = self._audio_input_device_name
            host_api = self._audio_input_device_host_api
            index_hint = self._audio_input_device

        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RecorderError(
                "sounddevice is not installed; wake-word listening is unavailable."
            ) from exc

        devices = list_audio_input_devices()
        resolved = resolve_input_device(name, host_api, index_hint, devices)
        self.last_resolution = resolved
        extras: dict[str, Any] = {}
        if resolved.index is not None:
            for device in devices:
                if device.index == resolved.index:
                    extras = input_stream_extra_settings(device.host_api)
                    break

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
        if resolved.index is not None:
            options["device"] = resolved.index
        options.update(extras)

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
                f"({exc.__class__.__name__}). "
                "Check microphone permissions.",
                details=(
                    f"{exc.__class__.__name__}: {exc}; "
                    f"device={resolved.index}; label={resolved.label}"
                ),
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

    def set_audio_input_device(self, value: object) -> None:
        selected_device = normalize_audio_input_device(value)
        with self._lock:
            if self._stream is not None:
                raise RecorderError(
                    "Stop wake-word listening before changing the microphone."
                )
            self._audio_input_device = selected_device

    def set_audio_input_selection(
        self,
        name: str | None,
        host_api: str | None,
        index_hint: object,
    ) -> None:
        selected_device = normalize_audio_input_device(index_hint)
        normalized_name = None if name is None else (str(name).strip() or None)
        normalized_host_api = (
            None if host_api is None else (str(host_api).strip() or None)
        )
        with self._lock:
            if self._stream is not None:
                raise RecorderError(
                    "Stop wake-word listening before changing the microphone."
                )
            self._audio_input_device_name = normalized_name
            self._audio_input_device_host_api = normalized_host_api
            self._audio_input_device = selected_device
