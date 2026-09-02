import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

import winwhisper.main as main_module
import winwhisper.update_controller as update_controller_module
from winwhisper.config import Settings, load_settings
from winwhisper.focus import ScreenPoint
from winwhisper.hotkeys import HotkeyActivationResult
from winwhisper.main import AppController
from winwhisper.transcriber import TranscriptionResult
from winwhisper.wake_word import (
    RollingBuffer,
    StopWordMonitor,
    WakeWordListener,
    audio_level,
    normalize_phrase,
    phrase_in_text,
    trim_trailing_phrase,
)


# --- phrase helpers ---------------------------------------------------------


def test_normalize_phrase_strips_punctuation_and_case():
    assert normalize_phrase("  Hey,  SPEECH! ") == "hey speech"
    assert normalize_phrase("stop.") == "stop"


def test_phrase_in_text_matches_whole_words_only():
    assert phrase_in_text("hey speech", "Hey, speech! Are you there?")
    assert phrase_in_text("hey speech", "hey speech")
    assert not phrase_in_text("hey speech", "hey speedy")
    assert not phrase_in_text("hey speech", "say speech")
    assert not phrase_in_text("", "anything")
    assert not phrase_in_text("hey speech", "")


def test_phrase_in_text_tolerates_one_letter_mishearing_in_long_words():
    # The tiny wake-word model's common mistakes still match.
    assert phrase_in_text("hey speech", "hey speach")
    assert phrase_in_text("hey speech", "hey speec")
    assert phrase_in_text("stop", "please stopp now")
    # Short words must stay exact, and two-letter errors must not match.
    assert not phrase_in_text("hey speech", "he speech")
    assert not phrase_in_text("hey speech", "hey speeds")
    assert not phrase_in_text("hey speech", "hay speech")


def test_trim_trailing_phrase_removes_only_a_tail_occurrence():
    assert trim_trailing_phrase("Send the file to Ana stop", "stop") == (
        "Send the file to Ana"
    )
    assert trim_trailing_phrase("Send the file to Ana, stop.", "stop") == (
        "Send the file to Ana,"
    )
    assert trim_trailing_phrase("stop", "stop") == ""
    assert trim_trailing_phrase("I love stopwatch timers", "stop") == (
        "I love stopwatch timers"
    )
    assert trim_trailing_phrase("stop talking then work stop talking", "stop talking") == (
        "stop talking then work"
    )
    assert trim_trailing_phrase("Nothing to trim", "") == "Nothing to trim"


def test_audio_level_scales_int16_rms():
    assert audio_level(np.zeros(100, dtype="int16")) == 0.0
    loud = np.full(100, 16384, dtype="int16")
    assert audio_level(loud) == pytest.approx(0.5, abs=0.01)


def test_boost_audio_scales_and_clips():
    from winwhisper.wake_word import boost_audio

    quiet = np.full(100, 400, dtype="int16")
    boosted = boost_audio(quiet, gain=8.0)
    assert boosted.dtype == np.int16
    assert int(boosted[0]) == 3200

    loud = np.full(100, 10_000, dtype="int16")
    assert int(boost_audio(loud, gain=8.0)[0]) == 32767

    assert int(boost_audio(np.array([-10_000], dtype="int16"), gain=8.0)[0]) == -32768


def test_detector_falls_back_to_cpu_when_device_fails(monkeypatch):
    import faster_whisper
    from winwhisper.wake_word import WhisperPhraseDetector

    attempts: list[tuple[str, str]] = []

    class FakeModel:
        def __init__(self, size, device=None, compute_type=None):
            attempts.append((device, compute_type))
            if device == "cuda":
                raise RuntimeError("no cuBLAS")

        def transcribe(self, audio, **kwargs):
            return [type("Seg", (), {"text": " hey speech "})()], None

    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeModel)

    detector = WhisperPhraseDetector(device="cuda", compute_type="float16")
    assert detector.detect(np.full(16_000, 400, dtype="int16")) == "hey speech"
    assert attempts == [("cuda", "float16"), ("cpu", "int8")]


def test_language_hints_from_settings():
    from winwhisper.wake_word import language_hints

    assert language_hints("es", ["en", "es", None]) == ["es", "en"]
    assert language_hints("auto", ["en", None, "en"]) == ["en"]
    assert language_hints("auto", [None, None, None]) == []
    assert language_hints("fr", []) == ["fr"]


def test_detect_phrase_tries_language_hints_until_a_transcript_matches(
    monkeypatch,
):
    import faster_whisper
    from winwhisper.wake_word import WhisperPhraseDetector

    calls: list[str | None] = []

    class AutoGetsItWrongModel:
        """Auto-detection hears English gibberish; the es hint hears right."""

        def __init__(self, size, device=None, compute_type=None):
            pass

        def transcribe(self, audio, language=None, **kwargs):
            calls.append(language)
            if language == "es":
                return [type("Seg", (), {"text": "oye speech"})()], None
            return [type("Seg", (), {"text": "OJ speech"})()], None

    monkeypatch.setattr(faster_whisper, "WhisperModel", AutoGetsItWrongModel)

    detector = WhisperPhraseDetector(languages=["es", "en"])
    audio = np.full(16_000, 400, dtype="int16")

    assert detector.detect_phrase(audio, ["oye speech"]) == "oye speech"
    assert calls == [None, "es"]

    calls.clear()

    class TalkativeModel:
        def __init__(self, size, device=None, compute_type=None):
            pass

        def transcribe(self, audio, language=None, **kwargs):
            calls.append(language)
            return [type("Seg", (), {"text": "hey speech"})()], None

    monkeypatch.setattr(faster_whisper, "WhisperModel", TalkativeModel)
    talkative = WhisperPhraseDetector(languages=["es", "en"])

    assert talkative.detect_phrase(audio, ["hey speech"]) == "hey speech"
    assert calls == [None]  # a match on the auto pass skips the hints

    calls.clear()
    assert talkative.detect_phrase(audio, ["oye speech"]) is None
    assert calls == [None, "es", "en"]  # no match tries every language


# --- RollingBuffer ----------------------------------------------------------


def test_rolling_buffer_keeps_only_the_most_recent_seconds():
    buffer = RollingBuffer(seconds=1.0)
    buffer.append(np.zeros(8_000, dtype="int16"))
    buffer.append(np.full(12_000, 7, dtype="int16"))

    snapshot = buffer.snapshot()

    assert snapshot.size == 16_000
    assert np.count_nonzero(snapshot) == 12_000
    assert snapshot[-1] == 7


def test_rolling_buffer_flattens_channel_dimension_and_clears():
    buffer = RollingBuffer(seconds=1.0)
    buffer.append(np.ones((160, 1), dtype="int16"))

    assert buffer.snapshot().shape == (160,)

    buffer.clear()
    assert buffer.snapshot().size == 0


def test_rolling_buffer_copies_incoming_blocks():
    # sounddevice hands out views into a reused ring buffer; mutating the
    # source array after append must not corrupt the stored samples.
    buffer = RollingBuffer(seconds=1.0)
    block = np.ones(160, dtype="int16")
    buffer.append(block)
    block[:] = 0

    assert int(buffer.snapshot().sum()) == 160


# --- config validators ------------------------------------------------------


def test_wake_word_settings_defaults_and_normalization():
    settings = Settings()

    assert settings.wake_word_enabled is False
    assert settings.wake_phrases == ["hey speech", "oye speech"]
    assert settings.stop_phrase == "stop"
    assert settings.wake_silence_timeout_seconds == 3.0

    assert Settings(wake_phrases=["Hey, Speech!", "oye  SPEECH"]).wake_phrases == [
        "hey speech",
        "oye speech",
    ]
    # A bare string is coerced into a one-phrase list.
    assert Settings(wake_phrases="Hey Computer").wake_phrases == ["hey computer"]
    assert Settings(wake_silence_timeout_seconds=0.1).wake_silence_timeout_seconds == 1.0
    assert Settings(wake_silence_timeout_seconds=99).wake_silence_timeout_seconds == 30.0
    assert Settings().wake_model_size == "tiny"
    assert Settings(wake_model_size="small").wake_model_size == "small"
    with pytest.raises(ValueError, match="must not be empty"):
        Settings(wake_model_size="  ")

    with pytest.raises(ValueError, match="At least one wake phrase"):
        Settings(wake_phrases=["!!!"])
    with pytest.raises(ValueError, match="at least one word"):
        Settings(stop_phrase="  ")


def test_wake_phrase_setting_migrates_to_list(monkeypatch, tmp_path):
    monkeypatch.setenv("WINWHISPER_APPDATA_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        '{"wake_phrase": "Hey Computer"}', encoding="utf-8"
    )

    loaded = load_settings()

    assert loaded.wake_phrases == ["hey computer"]


def test_wake_word_settings_round_trip(monkeypatch, tmp_path):
    monkeypatch.setenv("WINWHISPER_APPDATA_DIR", str(tmp_path))
    settings = Settings(wake_word_enabled=True, wake_phrases=["Hey Computer"])
    from winwhisper.config import save_settings

    save_settings(settings)

    loaded = load_settings()
    assert loaded.wake_word_enabled is True
    assert loaded.wake_phrases == ["hey computer"]


# --- WakeWordListener -------------------------------------------------------


class FakeSource:
    def __init__(self) -> None:
        self.on_block = None
        self.start_count = 0
        self.stop_count = 0

    def start(self, on_block) -> None:
        self.on_block = on_block
        self.start_count += 1

    def stop(self) -> None:
        self.stop_count += 1


class StubDetector:
    def __init__(self, transcripts) -> None:
        self._transcripts = list(transcripts)
        self.calls = 0

    def detect(self, audio) -> str:
        self.calls += 1
        if self._transcripts:
            return self._transcripts.pop(0)
        return ""

    def detect_phrase(self, audio, phrases) -> str | None:
        self.calls += 1
        if not self._transcripts:
            return None
        transcript = self._transcripts.pop(0)
        if any(phrase_in_text(phrase, transcript) for phrase in phrases):
            return transcript
        return None


def _loud_block(samples=16_000):
    return np.full(samples, 10_000, dtype="int16")


def test_listener_fires_on_wake_once_within_cooldown():
    source = FakeSource()
    detector = StubDetector(["hey speech start", "hey speech start"])
    hits = []
    listener = WakeWordListener(
        source,
        ["hey speech"],
        lambda: hits.append("hit"),
        detector=detector,
        poll_seconds=0.02,
        cooldown_seconds=60.0,
    )
    listener.start()
    try:
        source.on_block(_loud_block())
        deadline = time.monotonic() + 2.0
        while not hits and time.monotonic() < deadline:
            time.sleep(0.01)

        assert hits == ["hit"]
        time.sleep(0.15)
        assert hits == ["hit"]
    finally:
        listener.stop()

    assert source.start_count == 1
    assert source.stop_count >= 1


def test_listener_fires_on_any_configured_phrase():
    source = FakeSource()
    detector = StubDetector(["oye speech empecemos"])
    hits = []
    listener = WakeWordListener(
        source,
        ["hey speech", "oye speech"],
        lambda: hits.append("hit"),
        detector=detector,
        poll_seconds=0.02,
        cooldown_seconds=0.0,
    )
    listener.start()
    try:
        source.on_block(_loud_block())
        deadline = time.monotonic() + 2.0
        while not hits and time.monotonic() < deadline:
            time.sleep(0.01)

        assert hits == ["hit"]
    finally:
        listener.stop()


def test_listener_ignores_silence_without_calling_detector():
    source = FakeSource()
    detector = StubDetector(["hey speech"])
    listener = WakeWordListener(
        source,
        ["hey speech"],
        lambda: None,
        detector=detector,
        poll_seconds=0.02,
    )
    listener.start()
    try:
        source.on_block(np.zeros(16_000, dtype="int16"))
        time.sleep(0.1)
        assert detector.calls == 0
    finally:
        listener.stop()


def test_listener_pause_releases_source_and_resume_restarts_it():
    source = FakeSource()
    listener = WakeWordListener(
        source,
        ["hey speech"],
        lambda: None,
        detector=StubDetector([]),
        poll_seconds=0.02,
    )
    listener.start()
    listener.pause()

    assert source.stop_count == 1
    assert not listener.is_running()

    listener.resume()

    assert source.start_count == 2
    assert listener.is_running()
    listener.stop()


# --- StopWordMonitor --------------------------------------------------------


class FakeRecentRecorder:
    def __init__(self, samples) -> None:
        self._samples = samples

    def recent_audio(self, seconds):
        return self._samples


def _wait_for(event: threading.Event, seconds: float = 2.0) -> bool:
    return event.wait(seconds)


def test_stop_monitor_fires_on_stop_phrase():
    stopped: list[str] = []
    monitor = StopWordMonitor(
        FakeRecentRecorder(_loud_block()),
        "stop",
        30.0,
        lambda reason: stopped.append(reason),
        detector=StubDetector(["that is all stop"]),
        poll_seconds=0.02,
    )
    monitor.start()
    try:
        deadline = time.monotonic() + 2.0
        while not stopped and time.monotonic() < deadline:
            time.sleep(0.01)
        assert stopped == ["phrase"]
    finally:
        monitor.stop()


def test_stop_monitor_fires_after_silence_following_speech():
    recorder = FakeRecentRecorder(_loud_block())
    stopped: list[str] = []
    detector = StubDetector([])
    monitor = StopWordMonitor(
        recorder,
        "stop",
        0.05,
        lambda reason: stopped.append(reason),
        detector=detector,
        poll_seconds=0.02,
    )
    monitor.start()
    try:
        deadline = time.monotonic() + 2.0
        while detector.calls < 1 and time.monotonic() < deadline:
            time.sleep(0.005)
        recorder._samples = np.zeros(16_000, dtype="int16")

        deadline = time.monotonic() + 2.0
        while not stopped and time.monotonic() < deadline:
            time.sleep(0.01)
        assert stopped == ["silence"]
    finally:
        monitor.stop()


def test_stop_monitor_ignores_silence_before_any_speech():
    stopped: list[str] = []
    monitor = StopWordMonitor(
        FakeRecentRecorder(np.zeros(16_000, dtype="int16")),
        "stop",
        0.05,
        lambda reason: stopped.append(reason),
        detector=StubDetector([]),
        poll_seconds=0.02,
    )
    monitor.start()
    try:
        time.sleep(0.2)
        assert stopped == []
    finally:
        monitor.stop()


def test_stop_monitor_exits_when_recording_is_over():
    class EndedRecorder:
        def recent_audio(self, seconds):
            return None

    monitor = StopWordMonitor(
        EndedRecorder(),
        "stop",
        3.0,
        lambda reason: None,
        detector=StubDetector([]),
        poll_seconds=0.02,
    )
    monitor.start()
    thread = monitor._thread
    assert thread is not None
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    monitor.stop()


# --- AppController wiring ---------------------------------------------------


class FakeRecorder:
    def __init__(self, *args, **kwargs) -> None:
        self.recording = False
        self.recent_audio_capture = False

    def start_recording(self) -> None:
        self.recording = True

    def stop_recording(self):
        if not self.recording:
            return None
        self.recording = False
        return Path("fake-recording.wav")

    def is_recording(self) -> bool:
        return self.recording

    def current_level(self) -> float:
        return 0.0

    def recent_audio(self, seconds):
        return _loud_block() if self.recording else None

    def set_recent_audio_capture(self, enabled: bool) -> None:
        self.recent_audio_capture = bool(enabled)


class FakeTranscriber:
    text = "hola mundo stop"

    def __init__(self, settings, on_device_fallback=None) -> None:
        pass

    def is_model_loaded(self) -> bool:
        return True

    def ensure_model_loaded(self) -> None:
        return None

    def transcribe(self, audio_path, language_mode):
        return TranscriptionResult(
            text=self.text,
            language="es",
            language_probability=1.0,
            duration=1.0,
            model_size="small",
            device="cpu",
        )


class FakeTray:
    def __init__(self, controller) -> None:
        self.controller = controller
        self.notifications: list[tuple[str, str]] = []
        self.refresh_count = 0

    def run(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def set_status(self, status) -> None:
        return None

    def notify(self, title, message) -> None:
        self.notifications.append((title, message))

    def refresh_menu(self) -> None:
        self.refresh_count += 1


class FakeHotkeys:
    def __init__(self, hotkeys, on_hotkey) -> None:
        self.on_hotkey = on_hotkey

    def start(self) -> HotkeyActivationResult:
        return HotkeyActivationResult(active=(), failed=())

    def stop(self) -> None:
        return None

    def reset_trigger_state(self) -> None:
        return None


class FakeOverlay:
    def __init__(self, on_stop, level_provider=None) -> None:
        pass

    def show(self, anchor=None) -> None:
        return None

    def hide(self) -> None:
        return None

    def show_transcribing(self) -> None:
        return None

    def stop(self) -> None:
        return None


class FakeListener:
    instances: list["FakeListener"] = []

    def __init__(self, source, wake_phrase, on_wake, detector=None) -> None:
        self.wake_phrase = wake_phrase
        self.on_wake = on_wake
        self.started = False
        self.stopped = False
        self.paused = False
        self.instances.append(self)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False


class FakeMonitor:
    instances: list["FakeMonitor"] = []

    def __init__(
        self,
        recorder,
        stop_phrase,
        silence_timeout_seconds,
        on_stop,
        detector=None,
    ) -> None:
        self.stop_phrase = stop_phrase
        self.on_stop = on_stop
        self.started = False
        self.stopped = False
        self.instances.append(self)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class FakeWakeAudioSource:
    """No-op stand-in so controller tests never touch real audio backends.

    The macOS source spawns a worker thread in __init__, which ImmediateThread
    would otherwise run synchronously and hang the test.
    """

    def __init__(self, audio_input_device=None) -> None:
        pass

    def start(self, on_block) -> None:
        pass

    def stop(self) -> None:
        pass


class ImmediateThread:
    def __init__(self, target, args=(), **kwargs) -> None:
        self.target = target
        self.args = args

    def start(self) -> None:
        self.target(*self.args)


def make_controller(
    monkeypatch,
    tmp_path,
    inserted,
    wake_word_enabled=False,
    transcription_text="hola mundo stop",
):
    FakeListener.instances.clear()
    FakeMonitor.instances.clear()
    FakeTranscriber.text = transcription_text
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("WINWHISPER_APPDATA_DIR", str(tmp_path))
    monkeypatch.setattr(main_module, "Recorder", FakeRecorder)
    monkeypatch.setattr(main_module, "Transcriber", FakeTranscriber)
    monkeypatch.setattr(main_module, "TrayApp", FakeTray)
    monkeypatch.setattr(main_module, "HotkeyManager", FakeHotkeys)
    monkeypatch.setattr(main_module, "RecordingOverlay", FakeOverlay)
    monkeypatch.setattr(main_module, "WakeWordListener", FakeListener)
    monkeypatch.setattr(main_module, "WakeWordAudioSource", FakeWakeAudioSource)
    monkeypatch.setattr(main_module, "StopWordMonitor", FakeMonitor)
    monkeypatch.setattr(main_module, "get_foreground_window", lambda: 777)
    monkeypatch.setattr(main_module, "get_window_process_name", lambda hwnd: "notepad.exe")
    monkeypatch.setattr(main_module, "get_cursor_anchor", lambda hwnd: ScreenPoint(240, 320))
    monkeypatch.setattr(main_module, "restore_foreground_window", lambda hwnd: True)
    monkeypatch.setattr(
        main_module,
        "insert_text",
        lambda text, shortcut="ctrl_v": inserted.append((text, shortcut)) or True,
    )
    monkeypatch.setattr(main_module.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(
        update_controller_module, "fetch_latest_release", lambda current_version: None
    )
    monkeypatch.setattr(AppController, "_beep", lambda self, frequency, duration_ms: None)
    return AppController(
        Settings(
            language_mode="es",
            delete_audio_after_transcription=False,
            wake_word_enabled=wake_word_enabled,
        )
    )


def test_run_starts_listener_only_when_wake_word_enabled(monkeypatch, tmp_path):
    controller = make_controller(monkeypatch, tmp_path, [], wake_word_enabled=True)

    controller.run()

    assert len(FakeListener.instances) == 1
    assert FakeListener.instances[0].started is True


def test_run_without_wake_word_starts_no_listener(monkeypatch, tmp_path):
    controller = make_controller(monkeypatch, tmp_path, [], wake_word_enabled=False)

    controller.run()

    assert FakeListener.instances == []


def test_wake_word_starts_recording_and_pauses_listener(monkeypatch, tmp_path):
    controller = make_controller(monkeypatch, tmp_path, [], wake_word_enabled=True)
    controller._start_wake_listener()
    listener = FakeListener.instances[0]

    controller._on_wake_word()

    assert listener.paused is True
    assert controller.recorder.is_recording() is True
    assert controller.recorder.recent_audio_capture is True
    assert len(FakeMonitor.instances) == 1
    assert FakeMonitor.instances[0].started is True


def test_wake_word_ignored_while_recording(monkeypatch, tmp_path):
    controller = make_controller(monkeypatch, tmp_path, [], wake_word_enabled=True)
    controller._start_wake_listener()
    listener = FakeListener.instances[0]
    controller.toggle()
    assert controller.recorder.is_recording() is True

    controller._on_wake_word()

    assert listener.paused is False
    assert FakeMonitor.instances == []


def test_voice_stop_with_phrase_trims_stop_word_and_pastes(monkeypatch, tmp_path):
    inserted: list[tuple[str, str]] = []
    controller = make_controller(monkeypatch, tmp_path, inserted, wake_word_enabled=True)
    controller._start_wake_listener()
    listener = FakeListener.instances[0]
    controller._on_wake_word()
    monitor = FakeMonitor.instances[0]

    monitor.on_stop("phrase")

    assert inserted == [("Hola mundo", "ctrl_v")]
    assert listener.paused is False  # resumed after the paste completed
    assert monitor.stopped is True


def test_voice_stop_with_silence_pastes_untrimmed(monkeypatch, tmp_path):
    inserted: list[tuple[str, str]] = []
    controller = make_controller(
        monkeypatch,
        tmp_path,
        inserted,
        wake_word_enabled=True,
        transcription_text="hola mundo",
    )
    controller._start_wake_listener()
    controller._on_wake_word()
    monitor = FakeMonitor.instances[0]

    monitor.on_stop("silence")

    assert inserted == [("Hola mundo", "ctrl_v")]


def test_stop_phrase_only_recording_pastes_nothing(monkeypatch, tmp_path):
    inserted: list[tuple[str, str]] = []
    controller = make_controller(
        monkeypatch,
        tmp_path,
        inserted,
        wake_word_enabled=True,
        transcription_text="stop",
    )
    controller._start_wake_listener()
    controller._on_wake_word()
    monitor = FakeMonitor.instances[0]

    monitor.on_stop("phrase")

    assert inserted == []


def test_set_wake_word_enabled_toggles_listener_and_persists(monkeypatch, tmp_path):
    controller = make_controller(monkeypatch, tmp_path, [], wake_word_enabled=False)

    controller.set_wake_word_enabled(True)

    assert load_settings().wake_word_enabled is True
    assert len(FakeListener.instances) == 1
    assert FakeListener.instances[0].started is True

    controller.set_wake_word_enabled(False)

    assert load_settings().wake_word_enabled is False
    assert FakeListener.instances[0].stopped is True
