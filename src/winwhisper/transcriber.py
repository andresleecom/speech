from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .logger import get_logger


@dataclass
class TranscriptionResult:
    text: str
    language: str | None
    language_probability: float | None
    duration: float | None
    model_size: str
    device: str


def resolve_language(language_mode: str) -> str | None:
    if language_mode == "auto":
        return None
    if language_mode in {"en", "es"}:
        return language_mode

    get_logger(__name__).warning(
        "Unknown language mode %r; falling back to automatic detection.",
        language_mode,
    )
    return None


class Transcriber:
    def __init__(self, settings: Any) -> None:
        self._settings = settings
        self._model: Any | None = None
        self._model_size = str(settings.model_size)
        self._device = str(settings.device)
        self._compute_type = str(settings.compute_type)
        self._logger = get_logger(__name__)
        self._load_lock = threading.Lock()
    def is_model_loaded(self) -> bool:
        return self._model is not None

    def ensure_model_loaded(self) -> None:
        """Load the Whisper model if needed (safe to call from a warmup thread)."""
        self._load_model()

    def transcribe(self, audio_path: Path, language_mode: str) -> TranscriptionResult:
        self._logger.info(
            "Transcription starting (model_size=%s; device=%s; language_mode=%s; audio=%s).",
            self._model_size,
            self._device,
            language_mode,
            audio_path.name,
        )
        load_started = time.perf_counter()
        model = self._load_model()
        load_elapsed = time.perf_counter() - load_started
        if load_elapsed >= 0.05:
            self._logger.info("Model ready in %.2fs.", load_elapsed)

        language = resolve_language(language_mode)

        started_at = time.perf_counter()
        segments, info = model.transcribe(
            str(audio_path),
            language=language,
            vad_filter=True,
            beam_size=5,
        )
        text = " ".join(
            segment_text
            for segment_text in (
                getattr(segment, "text", "").strip() for segment in segments
            )
            if segment_text
        )
        elapsed = time.perf_counter() - started_at

        detected_language = getattr(info, "language", None)
        language_probability = getattr(info, "language_probability", None)
        duration = getattr(info, "duration", None)

        self._logger.info(
            "Transcription completed in %.2fs; detected_language=%s; audio_duration=%s.",
            elapsed,
            detected_language or "unknown",
            _format_duration(duration),
        )

        return TranscriptionResult(
            text=text,
            language=detected_language,
            language_probability=language_probability,
            duration=duration,
            model_size=self._model_size,
            device=self._device,
        )

    def _load_model(self) -> Any:
        with self._load_lock:
            if self._model is not None:
                return self._model

            from faster_whisper import WhisperModel

            self._logger.info(
                "Loading Whisper model (model_size=%s; device=%s; compute_type=%s).",
                self._model_size,
                self._device,
                self._compute_type,
            )
            started_at = time.perf_counter()
            try:
                self._model = WhisperModel(
                    self._model_size,
                    device=self._device,
                    compute_type=self._compute_type,
                )
            except Exception as exc:
                if self._device != "cuda":
                    raise

                self._logger.warning(
                    "CUDA model load failed with %s; falling back to CPU int8.",
                    exc.__class__.__name__,
                )
                self._device = "cpu"
                self._compute_type = "int8"
                self._model = WhisperModel(
                    self._model_size,
                    device=self._device,
                    compute_type=self._compute_type,
                )

            self._logger.info(
                "Whisper model loaded in %.2fs (device=%s; compute_type=%s).",
                time.perf_counter() - started_at,
                self._device,
                self._compute_type,
            )
            return self._model


def _format_duration(duration: float | None) -> str:
    if duration is None:
        return "unknown"
    return f"{duration:.2f}s"
