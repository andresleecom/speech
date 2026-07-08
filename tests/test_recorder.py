import pytest

from winwhisper.recorder import Recorder, _audio_level_from_block


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
