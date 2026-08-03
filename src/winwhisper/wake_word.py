"""Hands-free wake-word detection built on a rolling tiny-Whisper window.

This module is platform-agnostic: audio arrives as 16 kHz mono int16 numpy
blocks pushed by an ``AudioSource`` (see ``wake_word_source.py`` and
``wake_word_source_mac.py``), and recording audio is read back through the
recorder's ``recent_audio`` method. Everything here communicates through
callbacks so the module stays free of ``main.py`` imports.
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any, Protocol

from .logger import get_logger

SAMPLE_RATE = 16_000
INT16_PEAK = 32768.0

# How much audio the wake listener transcribes on each pass.
WAKE_WINDOW_SECONDS = 4.0
WAKE_POLL_SECONDS = 0.8
WAKE_COOLDOWN_SECONDS = 2.0

# Stop-word monitoring while a hands-free recording is active.
STOP_POLL_SECONDS = 1.0
STOP_TAIL_SECONDS = 2.5

# RMS threshold (0..1, int16 scale) separating speech from background noise.
SPEECH_LEVEL_THRESHOLD = 0.01

# Digital gain applied before detection. Some microphones deliver a very low
# signal (e.g. broadcast dynamics at modest gain); the tiny model and its VAD
# need a healthier level than the main small model does.
WAKE_GAIN = 8.0

_WHISPER_MODEL_SIZE = "tiny"
_CPU_FALLBACK = ("cpu", "int8")


class AudioSource(Protocol):
    """Pushes 16 kHz mono int16 numpy blocks to a callback until stopped."""

    def start(self, on_block: Callable[[Any], None]) -> None: ...

    def stop(self) -> None: ...


def normalize_phrase(text: object) -> str:
    """Lowercase and reduce to space-separated words for phrase matching."""
    normalized = re.sub(r"[^\w\s]", " ", str(text), flags=re.UNICODE)
    return " ".join(normalized.lower().split())


def _levenshtein_at_most(a: str, b: str, max_dist: int) -> bool:
    """True when the edit distance between two words is at most max_dist."""
    if abs(len(a) - len(b)) > max_dist:
        return False
    row = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        new_row = [i]
        row_min = i
        for j, char_b in enumerate(b, start=1):
            cost = 0 if char_a == char_b else 1
            cell = min(row[j] + 1, new_row[j - 1] + 1, row[j - 1] + cost)
            new_row.append(cell)
            row_min = min(row_min, cell)
        if row_min > max_dist:
            return False
        row = new_row
    return row[-1] <= max_dist


def phrase_in_text(phrase: str, text: str) -> bool:
    """Whole-word substring match of a normalized phrase inside text.

    Besides exact matching, tolerates a one-letter mishearing in words of
    four or more characters ("hey speach", "hey speec") — the tiny wake-word
    model's most common mistakes. Short words like "hey" must match exactly.
    """
    needle = normalize_phrase(phrase)
    haystack = normalize_phrase(text)
    if not needle or not haystack:
        return False
    if re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", haystack) is not None:
        return True

    needle_words = needle.split()
    words = haystack.split()
    for start in range(0, len(words) - len(needle_words) + 1):
        window = words[start : start + len(needle_words)]
        if all(
            wanted == heard
            or (len(wanted) >= 4 and _levenshtein_at_most(wanted, heard, 1))
            for wanted, heard in zip(needle_words, window)
        ):
            return True
    return False


def trim_trailing_phrase(text: str, phrase: str) -> str:
    """Remove a trailing spoken stop phrase from a transcript.

    Matches the phrase words in order at the end of the text, tolerating
    punctuation between them ("... my email, stop." -> "... my email").
    Non-trailing occurrences and longer words ("stopwatch") are untouched.
    """
    words = normalize_phrase(phrase).split()
    if not words:
        return text
    pattern = (
        r"(?<!\w)"
        + r"\W+".join(re.escape(word) for word in words)
        + r"(?!\w)\W*$"
    )
    trimmed = re.sub(pattern, "", text, flags=re.IGNORECASE).rstrip()
    return trimmed


def audio_level(block: Any) -> float:
    """RMS level of an int16 block on a 0..1 scale."""
    try:
        import numpy as np

        samples = np.asarray(block, dtype="float32").reshape(-1) / INT16_PEAK
        if samples.size == 0:
            return 0.0
        rms = float(np.sqrt(np.mean(np.square(samples))))
        return min(1.0, max(0.0, rms))
    except Exception:
        return 0.0


def boost_audio(audio_int16: Any, gain: float = WAKE_GAIN) -> Any:
    """Scale int16 samples by a fixed digital gain, clipping at full scale."""
    import numpy as np

    samples = np.asarray(audio_int16, dtype="float32") * gain
    return np.clip(samples, -32768, 32767).astype("int16")


class RollingBuffer:
    """Thread-safe deque of int16 blocks capped to the most recent seconds."""

    def __init__(self, seconds: float = WAKE_WINDOW_SECONDS) -> None:
        self._max_samples = max(1, int(seconds * SAMPLE_RATE))
        self._blocks: deque[Any] = deque()
        self._sample_count = 0
        self._lock = threading.Lock()

    def append(self, block: Any) -> None:
        import numpy as np

        # Copy: sounddevice passes views into PortAudio's ring buffer, which
        # is reused as soon as the callback returns.
        samples = np.array(block, dtype="int16").reshape(-1)
        if samples.size == 0:
            return
        with self._lock:
            self._blocks.append(samples)
            self._sample_count += int(samples.size)
            while self._sample_count > self._max_samples and self._blocks:
                oldest = self._blocks[0]
                overflow = self._sample_count - self._max_samples
                if oldest.size <= overflow:
                    self._blocks.popleft()
                    self._sample_count -= int(oldest.size)
                else:
                    self._blocks[0] = oldest[overflow:]
                    self._sample_count -= overflow

    def snapshot(self) -> Any:
        import numpy as np

        with self._lock:
            if not self._blocks:
                return np.empty(0, dtype="int16")
            return np.concatenate(list(self._blocks))

    def clear(self) -> None:
        with self._lock:
            self._blocks.clear()
            self._sample_count = 0


def language_hints(language_mode: str, language_favorites: object) -> list[str]:
    """Ordered language hints for the wake detector from the user's settings.

    The configured single language (when not auto) goes first, followed by
    the language favorites; blanks and duplicates are removed.
    """
    from .languages import AUTO_LANGUAGE_MODE

    hints: list[str] = []
    if language_mode and language_mode != AUTO_LANGUAGE_MODE:
        hints.append(language_mode)
    for favorite in language_favorites or ():
        if favorite and favorite not in hints:
            hints.append(str(favorite))
    return hints


class WhisperPhraseDetector:
    """Shared, lazily loaded tiny-Whisper model for short-window detection.

    Follows the app's device/compute_type (e.g. CUDA) for fast detection and
    falls back to CPU int8 if the requested device cannot load the model.

    ``languages`` (e.g. the user's language favorites) matter because
    auto-detection can lock onto the wrong language for short phrases: a
    Spanish "oye speech" auto-detected as English comes out as "OJ speech".
    So each window is tried with auto-detection first and then with every
    hint until a transcript matches one of the target phrases.
    """

    def __init__(
        self,
        device: str = "cpu",
        compute_type: str = "int8",
        languages: list[str] | None = None,
        model_size: str = _WHISPER_MODEL_SIZE,
    ) -> None:
        self._model: Any | None = None
        self._device = device
        self._compute_type = compute_type
        self._languages = list(languages or ())
        self._model_size = model_size
        self._lock = threading.Lock()
        self._logger = get_logger(__name__)

    def detect(self, audio_int16: Any) -> str:
        """Auto-detected transcript of a short int16 buffer (testing helper)."""
        import numpy as np

        audio = np.asarray(audio_int16, dtype="int16").reshape(-1)
        if audio.size < SAMPLE_RATE // 2:
            return ""
        audio_float = audio.astype("float32") / INT16_PEAK
        with self._lock:
            return self._run_with_fallback(audio_float, language=None)

    def detect_phrase(self, audio_int16: Any, phrases: list[str]) -> str | None:
        """Return the first transcript matching any of the phrases, or None.

        Tries auto-detection first, then each language hint, stopping at the
        first match — English speech matches on the auto pass (one
        inference), other languages on their hint pass.
        """
        import numpy as np

        audio = np.asarray(audio_int16, dtype="int16").reshape(-1)
        if audio.size < SAMPLE_RATE // 2:
            return None
        audio_float = audio.astype("float32") / INT16_PEAK
        with self._lock:
            for language in [None, *self._languages]:
                transcript = self._run_with_fallback(audio_float, language=language)
                if not transcript:
                    continue
                self._logger.debug(
                    "Wake-word window heard %r (language=%s).",
                    transcript[:120],
                    language or "auto",
                )
                if any(phrase_in_text(phrase, transcript) for phrase in phrases):
                    return transcript
        return None

    def _run_with_fallback(self, audio_float: Any, language: str | None) -> str:
        try:
            return self._run_model(audio_float, language)
        except Exception:
            if (self._device, self._compute_type) == _CPU_FALLBACK:
                raise
            self._logger.warning(
                "Wake-word detection failed on %s; retrying on CPU %s.",
                self._device,
                _CPU_FALLBACK[1],
            )
            self._model = None
            self._device, self._compute_type = _CPU_FALLBACK
            return self._run_model(audio_float, language)

    def _run_model(self, audio_float: Any, language: str | None) -> str:
        model = self._load_model()
        segments, _info = model.transcribe(
            audio_float,
            beam_size=1,
            vad_filter=True,
            language=language,
        )
        return " ".join(
            segment_text
            for segment_text in (
                getattr(segment, "text", "").strip() for segment in segments
            )
            if segment_text
        )

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        from faster_whisper import WhisperModel

        try:
            self._logger.info(
                "Loading wake-word model (model_size=%s; device=%s; compute_type=%s).",
                self._model_size,
                self._device,
                self._compute_type,
            )
            self._model = WhisperModel(
                self._model_size,
                device=self._device,
                compute_type=self._compute_type,
            )
        except Exception:
            if (self._device, self._compute_type) == _CPU_FALLBACK:
                raise
            self._logger.warning(
                "Wake-word model could not load on %s; falling back to CPU %s.",
                self._device,
                _CPU_FALLBACK[1],
            )
            self._device, self._compute_type = _CPU_FALLBACK
            self._model = WhisperModel(
                self._model_size,
                device=self._device,
                compute_type=self._compute_type,
            )
        return self._model


class WakeWordListener:
    """Always-on listener that fires ``on_wake`` when the wake phrase is heard."""

    def __init__(
        self,
        source: AudioSource,
        wake_phrases: list[str],
        on_wake: Callable[[], None],
        detector: WhisperPhraseDetector | None = None,
        poll_seconds: float = WAKE_POLL_SECONDS,
        cooldown_seconds: float = WAKE_COOLDOWN_SECONDS,
    ) -> None:
        self._source = source
        self._wake_phrases = list(wake_phrases)
        self._on_wake = on_wake
        self._detector = detector or WhisperPhraseDetector()
        self._poll_seconds = poll_seconds
        self._cooldown_seconds = cooldown_seconds
        self._buffer = RollingBuffer()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._paused = False
        self._started = False
        self._last_hit_at = 0.0
        self._thread: threading.Thread | None = None
        self._logger = get_logger(__name__)

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            self._paused = False
            self._stop_event.clear()
            self._buffer.clear()
        self._source.start(self._buffer.append)
        self._thread = threading.Thread(
            target=self._run,
            name="winwhisper-wake-word",
            daemon=True,
        )
        self._thread.start()
        self._logger.info(
            "Wake-word listener started (phrases=%r).", self._wake_phrases
        )

    def stop(self) -> None:
        with self._lock:
            if not self._started:
                return
            self._started = False
        self._stop_event.set()
        self._source.stop()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5.0)
        self._thread = None
        self._logger.info("Wake-word listener stopped.")

    def pause(self) -> None:
        """Release the microphone while a recording owns it."""
        with self._lock:
            if not self._started or self._paused:
                return
            self._paused = True
        self._source.stop()
        self._buffer.clear()

    def resume(self) -> None:
        with self._lock:
            if not self._started or not self._paused:
                return
            self._paused = False
            self._last_hit_at = time.monotonic()
            self._buffer.clear()
        self._source.start(self._buffer.append)

    def is_running(self) -> bool:
        with self._lock:
            return self._started and not self._paused

    def _run(self) -> None:
        while not self._stop_event.wait(self._poll_seconds):
            try:
                self._detect_once()
            except Exception:
                self._logger.exception("Wake-word detection pass failed.")

    def _detect_once(self) -> None:
        with self._lock:
            if not self._started or self._paused:
                return
        audio = boost_audio(self._buffer.snapshot())
        level = audio_level(audio)
        if audio.size < SAMPLE_RATE or level < SPEECH_LEVEL_THRESHOLD:
            return
        matched = self._detector.detect_phrase(audio, self._wake_phrases)
        if matched is None:
            return
        now = time.monotonic()
        with self._lock:
            if now - self._last_hit_at < self._cooldown_seconds:
                return
            self._last_hit_at = now
        self._logger.info(
            "Wake phrase heard (transcript=%r).", matched[:120]
        )
        self._on_wake()


class StopWordMonitor:
    """Watches a live recording for the stop phrase or a silence timeout."""

    def __init__(
        self,
        recorder: Any,
        stop_phrase: str,
        silence_timeout_seconds: float,
        on_stop: Callable[[str], None],
        detector: WhisperPhraseDetector | None = None,
        poll_seconds: float = STOP_POLL_SECONDS,
        tail_seconds: float = STOP_TAIL_SECONDS,
    ) -> None:
        self._recorder = recorder
        self._stop_phrase = stop_phrase
        self._silence_timeout_seconds = silence_timeout_seconds
        self._on_stop = on_stop
        self._detector = detector or WhisperPhraseDetector()
        self._poll_seconds = poll_seconds
        self._tail_seconds = tail_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._logger = get_logger(__name__)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="winwhisper-stop-word",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5.0)
        self._thread = None

    def _run(self) -> None:
        speech_seen = False
        silence_seconds = 0.0
        while not self._stop_event.wait(self._poll_seconds):
            try:
                audio = self._recorder.recent_audio(self._tail_seconds)
            except Exception:
                self._logger.exception("Could not read recent recording audio.")
                continue
            if audio is None:
                # Recording already ended through another path.
                return
            try:
                audio = boost_audio(audio)
                level = audio_level(audio)
                if level >= SPEECH_LEVEL_THRESHOLD:
                    speech_seen = True
                    silence_seconds = 0.0
                    matched = self._detector.detect_phrase(audio, [self._stop_phrase])
                    if matched is not None:
                        self._logger.info(
                            "Stop phrase heard (transcript=%r).", matched[:120]
                        )
                        self._on_stop("phrase")
                        return
                elif speech_seen:
                    silence_seconds += self._poll_seconds
                    if silence_seconds >= self._silence_timeout_seconds:
                        self._logger.info(
                            "Silence for %.1fs after speech; auto-stopping.",
                            silence_seconds,
                        )
                        self._on_stop("silence")
                        return
            except Exception:
                self._logger.exception("Stop-word detection pass failed.")
