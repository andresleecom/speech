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
# The stop phrase is only evaluated once the user has paused after speaking.
STOP_TRAILING_QUIET_SECONDS = 0.5

# RMS threshold (0..1, int16 scale) separating speech from background noise.
SPEECH_LEVEL_THRESHOLD = 0.01

# Silero VAD: ignore clicks shorter than this before calling the tiny model.
VAD_MIN_SPEECH_MS = 250

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


def _words_match_fuzzy(wanted: str, heard: str) -> bool:
    """Exact match, or 1-edit fuzziness for words of five or more letters."""
    return wanted == heard or (
        len(wanted) >= 5 and _levenshtein_at_most(wanted, heard, 1)
    )


def _words_match_with_short_slip(wanted: str, heard: str) -> bool:
    """Existing fuzzy rule, plus 1-edit for words of three or four letters."""
    if _words_match_fuzzy(wanted, heard):
        return True
    return 3 <= len(wanted) <= 4 and _levenshtein_at_most(wanted, heard, 1)


def phrase_in_text(
    phrase: str, text: str, *, allow_short_slip: bool = False
) -> bool:
    """Whole-word substring match of a normalized phrase inside text.

    Besides exact matching, tolerates a one-letter mishearing in words of
    five or more characters ("hey speach", "hey speec") - the tiny wake-word
    model's most common mistakes. Short words like "hey" and "stop" must
    match exactly by default, so "stop" does not match "step" or "shop".

    When ``allow_short_slip`` is True and the phrase has two or more words,
    a three- or four-letter word may also slip by one edit, but only if at
    least one word in the candidate window matches exactly ("oje speech"
    for "oye speech"; not "oje spich").
    """
    needle = normalize_phrase(phrase)
    haystack = normalize_phrase(text)
    if not needle or not haystack:
        return False
    if re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", haystack) is not None:
        return True

    needle_words = needle.split()
    words = haystack.split()
    use_short_slip = allow_short_slip and len(needle_words) >= 2
    for start in range(0, len(words) - len(needle_words) + 1):
        window = words[start : start + len(needle_words)]
        if use_short_slip:
            pairs = list(zip(needle_words, window))
            if all(
                _words_match_with_short_slip(wanted, heard)
                for wanted, heard in pairs
            ) and any(wanted == heard for wanted, heard in pairs):
                return True
        elif all(
            _words_match_fuzzy(wanted, heard)
            for wanted, heard in zip(needle_words, window)
        ):
            return True
    return False


def phrase_is_trailing(phrase: str, text: str) -> bool:
    """True when the phrase is the last words of the text (same fuzziness)."""
    needle = normalize_phrase(phrase)
    haystack = normalize_phrase(text)
    if not needle or not haystack:
        return False
    needle_words = needle.split()
    words = haystack.split()
    if len(words) < len(needle_words):
        return False
    window = words[-len(needle_words) :]
    return all(
        _words_match_fuzzy(wanted, heard)
        for wanted, heard in zip(needle_words, window)
    )


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


def _audio_to_float32(audio_int16: Any) -> Any:
    import numpy as np

    return np.asarray(audio_int16, dtype="int16").reshape(-1).astype("float32") / INT16_PEAK


def _speech_timestamps(audio_int16: Any) -> list[dict[str, Any]]:
    """Silero VAD speech segments for a 16 kHz int16 buffer (already boosted)."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    audio_float = _audio_to_float32(audio_int16)
    if audio_float.size == 0:
        return []
    return get_speech_timestamps(
        audio_float,
        vad_options=VadOptions(min_speech_duration_ms=VAD_MIN_SPEECH_MS),
        sampling_rate=SAMPLE_RATE,
    )


def has_speech(audio_int16: Any) -> bool:
    """True when Silero VAD finds at least one speech segment in the buffer."""
    try:
        return bool(_speech_timestamps(audio_int16))
    except Exception:
        return False


def phrases_initial_prompt(phrases: list[str]) -> str:
    """Build an initial_prompt from wake/stop phrases as capitalised sentences."""
    parts: list[str] = []
    for phrase in phrases:
        normalized = normalize_phrase(phrase)
        if not normalized:
            continue
        capitalised = normalized[:1].upper() + normalized[1:]
        parts.append(f"{capitalised}.")
    return " ".join(parts)


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

    Each window is transcribed once with the target phrases as
    ``initial_prompt`` so short multilingual cues ("oye speech") land
    correctly without a language-hint retry loop. ``languages`` is still
    accepted for constructor compatibility but ignored.
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
        self._languages = list(languages or ())  # kept, unused
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
            return self._run_with_fallback(audio_float)

    def detect_phrase(self, audio_int16: Any, phrases: list[str]) -> str | None:
        """Return the matched phrase after one prompted pass, or None."""
        matched, _transcript = self.detect_transcript(audio_int16, phrases)
        return matched

    def detect_transcript(
        self, audio_int16: Any, phrases: list[str]
    ) -> tuple[str | None, str]:
        """Return ``(matched_phrase | None, transcript)`` after one prompted pass."""
        import numpy as np

        audio = np.asarray(audio_int16, dtype="int16").reshape(-1)
        if audio.size < SAMPLE_RATE // 2:
            return None, ""
        audio_float = audio.astype("float32") / INT16_PEAK
        prompt = phrases_initial_prompt(phrases)
        with self._lock:
            transcript = self._run_with_fallback(
                audio_float, initial_prompt=prompt or None
            )
        if transcript:
            self._logger.info("Wake-word window heard %r", transcript)
            for phrase in phrases:
                if phrase_in_text(phrase, transcript, allow_short_slip=True):
                    return phrase, transcript
        return None, transcript

    def _run_with_fallback(
        self,
        audio_float: Any,
        language: str | None = None,
        initial_prompt: str | None = None,
    ) -> str:
        try:
            return self._run_model(audio_float, language, initial_prompt)
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
            return self._run_model(audio_float, language, initial_prompt)

    def _run_model(
        self,
        audio_float: Any,
        language: str | None = None,
        initial_prompt: str | None = None,
    ) -> str:
        model = self._load_model()
        segments, _info = model.transcribe(
            audio_float,
            beam_size=1,
            vad_filter=True,
            language=language,
            initial_prompt=initial_prompt,
            condition_on_previous_text=False,
            temperature=0.0,
            compression_ratio_threshold=None,
            log_prob_threshold=None,
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
    """Always-on listener that fires ``on_wake(phrase)`` when a wake phrase is heard."""

    def __init__(
        self,
        source: AudioSource,
        wake_phrases: list[str],
        on_wake: Callable[[str], None],
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
        if not has_speech(audio):
            return
        matched = self._detector.detect_phrase(audio, self._wake_phrases)
        if matched is None:
            return
        now = time.monotonic()
        with self._lock:
            if now - self._last_hit_at < self._cooldown_seconds:
                return
            self._last_hit_at = now
        self._logger.info("Wake phrase heard (phrase=%r).", matched)
        self._on_wake(matched)


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
        last_speech_at: float | None = None
        quiet_samples = max(1, int(STOP_TRAILING_QUIET_SECONDS * SAMPLE_RATE))
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
                now = time.monotonic()
                segments = _speech_timestamps(audio)
                if segments:
                    speech_seen = True
                    last_end = int(segments[-1]["end"])
                    silence_at_end = max(0.0, (int(audio.size) - last_end) / SAMPLE_RATE)
                    last_speech_at = now - silence_at_end
                elif speech_seen and last_speech_at is None:
                    last_speech_at = now - self._tail_seconds

                trailing = audio[-quiet_samples:] if audio.size else audio
                trailing_quiet = audio_level(trailing) < SPEECH_LEVEL_THRESHOLD
                if speech_seen and trailing_quiet:
                    _matched, transcript = self._detector.detect_transcript(
                        audio, [self._stop_phrase]
                    )
                    if phrase_is_trailing(self._stop_phrase, transcript):
                        self._logger.info(
                            "Stop phrase heard (transcript=%r).", transcript[:120]
                        )
                        self._on_stop("phrase")
                        return

                if (
                    speech_seen
                    and last_speech_at is not None
                    and now - last_speech_at >= self._silence_timeout_seconds
                ):
                    self._logger.info(
                        "Silence for %.1fs after speech; auto-stopping.",
                        now - last_speech_at,
                    )
                    self._on_stop("silence")
                    return
            except Exception:
                self._logger.exception("Stop-word detection pass failed.")
