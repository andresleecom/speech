import pytest

from winwhisper.recorder import (
    MicrophoneTest,
    Recorder,
    RecorderError,
    _audio_level_from_block,
)


class FakeInputStream:
    instances: list["FakeInputStream"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.started = False
        self.stopped = False
        self.closed = False
        self.instances.append(self)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


def install_fake_sounddevice(monkeypatch):
    import sys
    import types

    FakeInputStream.instances.clear()
    sounddevice = types.SimpleNamespace(InputStream=FakeInputStream)
    monkeypatch.setitem(sys.modules, "sounddevice", sounddevice)


def test_audio_level_from_silent_block_is_zero():
    import numpy as np

    block = np.zeros((4, 1), dtype="int16")

    assert _audio_level_from_block(block) == 0.0


def test_audio_level_from_int16_block_is_normalized_rms():
    import numpy as np

    block = np.array([[16384], [-16384]], dtype="int16")

    assert _audio_level_from_block(block) == pytest.approx(0.5, abs=0.01)


def test_recorder_current_level_tracks_recent_blocks():
    import numpy as np

    recorder = Recorder()
    recorder._record_block(np.array([[32767], [32767]], dtype="int16"))
    loud_level = recorder.current_level()

    recorder._record_block(np.zeros((2, 1), dtype="int16"))

    assert loud_level > 0.9
    assert 0.0 < recorder.current_level() < loud_level


def test_stop_recording_is_idempotent_when_not_recording():
    recorder = Recorder()
    assert recorder.stop_recording() is None


def test_recorder_caps_samples_at_max(monkeypatch):
    import numpy as np

    calls: list[str] = []
    recorder = Recorder(max_samples=4, on_max_duration=lambda: calls.append("limit"))
    recorder._record_block(np.ones((3, 1), dtype="int16"))
    recorder._record_block(np.ones((3, 1), dtype="int16"))
    recorder._record_block(np.ones((3, 1), dtype="int16"))

    assert recorder.max_duration_reached() is True
    assert calls == ["limit"]
    with recorder._lock:
        total = sum(int(block.shape[0]) for block in recorder._blocks)
    assert total == 4


def test_recorder_uses_saved_audio_input_device(monkeypatch):
    install_fake_sounddevice(monkeypatch)
    recorder = Recorder(audio_input_device=3)

    recorder.start_recording()

    assert FakeInputStream.instances[-1].kwargs["device"] == 3
    recorder.stop_recording().unlink()


def test_recorder_omits_device_for_system_default(monkeypatch):
    install_fake_sounddevice(monkeypatch)
    recorder = Recorder()

    recorder.start_recording()

    assert "device" not in FakeInputStream.instances[-1].kwargs
    recorder.stop_recording().unlink()


def test_recorder_cannot_change_input_while_recording(monkeypatch):
    install_fake_sounddevice(monkeypatch)
    recorder = Recorder()
    recorder.start_recording()

    with pytest.raises(RecorderError, match="Stop dictation"):
        recorder.set_audio_input_device(2)

    recorder.stop_recording().unlink()


def test_recorder_reports_actionable_recovery_when_default_input_cannot_open(monkeypatch):
    import sys
    import types

    class FailingInputStream:
        def __init__(self, **kwargs) -> None:
            raise OSError("permission denied")

    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        types.SimpleNamespace(InputStream=FailingInputStream),
    )
    recorder = Recorder()

    with pytest.raises(RecorderError, match="Check microphone permissions"):
        recorder.start_recording()


def test_microphone_test_reports_live_level_without_writing_audio(monkeypatch):
    import numpy as np

    install_fake_sounddevice(monkeypatch)
    microphone_test = MicrophoneTest(audio_input_device=2)

    microphone_test.start()
    stream = FakeInputStream.instances[-1]
    stream.kwargs["callback"](
        np.array([[16384], [-16384]], dtype="int16"),
        2,
        None,
        None,
    )

    assert stream.kwargs["device"] == 2
    assert microphone_test.current_level() == pytest.approx(0.5, abs=0.01)
    assert microphone_test.stop() == pytest.approx(0.5, abs=0.01)
    assert stream.stopped is True
    assert stream.closed is True
