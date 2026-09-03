import pytest

from winwhisper.audio_inputs import AudioInputDevice, ResolvedInputDevice
from winwhisper.recorder import (
    MicrophoneTest,
    Recorder,
    RecorderError,
    TakeStats,
    _audio_level_from_block,
)


class FakeInputStream:
    instances: list["FakeInputStream"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.started = False
        self.aborted = False
        self.abort_ignore_errors = None
        self.closed = False
        self.close_ignore_errors = None
        self.instances.append(self)

    def start(self) -> None:
        self.started = True

    def abort(self, ignore_errors=False) -> None:
        self.aborted = True
        self.abort_ignore_errors = ignore_errors

    def close(self, ignore_errors=False) -> None:
        self.closed = True
        self.close_ignore_errors = ignore_errors


@pytest.fixture(autouse=True)
def isolate_app_data(monkeypatch, tmp_path):
    monkeypatch.setenv("WINWHISPER_APPDATA_DIR", str(tmp_path))


def install_fake_sounddevice(monkeypatch):
    import sys
    import types

    import winwhisper.audio_inputs as audio_inputs

    FakeInputStream.instances.clear()
    sounddevice = types.SimpleNamespace(
        InputStream=FakeInputStream,
        _terminate=lambda: None,
        _initialize=lambda: None,
        query_devices=lambda: [],
        query_hostapis=lambda index: {"name": "MME"},
    )
    monkeypatch.setitem(sys.modules, "sounddevice", sounddevice)
    # Force the PortAudio refresh path so refresh_ms assertions work on macOS CI,
    # where _use_native_macos_audio() would otherwise skip refresh by design.
    monkeypatch.setattr(audio_inputs, "_use_native_macos_audio", lambda: False)


@pytest.fixture(autouse=True)
def reset_open_stream_counter():
    import winwhisper.audio_inputs as audio_inputs

    with audio_inputs._open_stream_lock:
        audio_inputs._open_stream_count = 0
    yield
    with audio_inputs._open_stream_lock:
        audio_inputs._open_stream_count = 0


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
    monkeypatch.setattr(
        "winwhisper.recorder.list_audio_input_devices",
        lambda: (
            AudioInputDevice(
                index=3, name="USB Mic", input_channels=1, host_api="MME"
            ),
        ),
    )
    monkeypatch.setattr(
        "winwhisper.recorder.resolve_input_device",
        lambda name, host_api, index_hint, devices=None: ResolvedInputDevice(
            index=3, label="USB Mic [3]", fallback=False, reason=""
        ),
    )
    recorder = Recorder(audio_input_device=3)
    recorder.set_audio_input_selection("USB Mic", "MME", 3)

    recorder.start_recording()

    assert FakeInputStream.instances[-1].kwargs["device"] == 3
    stream = FakeInputStream.instances[-1]
    recorder.stop_recording().unlink()

    assert stream.aborted is True
    assert stream.abort_ignore_errors is False
    assert stream.closed is True
    assert stream.close_ignore_errors is True
    assert recorder.last_resolution is not None
    assert recorder.last_resolution.index == 3


def test_recorder_stale_hint_resolves_by_name(monkeypatch):
    install_fake_sounddevice(monkeypatch)
    devices = (
        AudioInputDevice(
            index=2, name="PodMic", input_channels=1, host_api="MME"
        ),
    )
    monkeypatch.setattr("winwhisper.recorder.list_audio_input_devices", lambda: devices)
    monkeypatch.setattr(
        "winwhisper.recorder.resolve_input_device",
        lambda name, host_api, index_hint, devices=None: ResolvedInputDevice(
            index=2, label="PodMic [2]", fallback=False, reason=""
        ),
    )
    recorder = Recorder(audio_input_device=3)
    recorder.set_audio_input_selection("PodMic", "MME", 3)
    recorder.start_recording()
    assert FakeInputStream.instances[-1].kwargs["device"] == 2
    recorder.stop_recording().unlink()


def test_recorder_passes_wasapi_extra_settings(monkeypatch):
    class WasapiSettings:
        def __init__(self, auto_convert=False) -> None:
            self.auto_convert = auto_convert

    install_fake_sounddevice(monkeypatch)
    import sys

    sounddevice = sys.modules["sounddevice"]
    sounddevice.WasapiSettings = WasapiSettings
    devices = (
        AudioInputDevice(
            index=27, name="PodMic", input_channels=1, host_api="Windows WASAPI"
        ),
    )
    monkeypatch.setattr("winwhisper.recorder.list_audio_input_devices", lambda: devices)
    monkeypatch.setattr(
        "winwhisper.recorder.resolve_input_device",
        lambda name, host_api, index_hint, devices=None: ResolvedInputDevice(
            index=27, label="PodMic [27]", fallback=False, reason=""
        ),
    )
    monkeypatch.setattr(
        "winwhisper.recorder.input_stream_extra_settings",
        lambda host_api: {"extra_settings": WasapiSettings(auto_convert=True)}
        if host_api == "Windows WASAPI"
        else {},
    )
    recorder = Recorder()
    recorder.set_audio_input_selection("PodMic", "Windows WASAPI", 27)
    recorder.start_recording()
    extras = FakeInputStream.instances[-1].kwargs.get("extra_settings")
    assert extras is not None
    assert extras.auto_convert is True
    recorder.stop_recording().unlink()


def test_recorder_error_includes_portaudio_details(monkeypatch):
    class FailingInputStream:
        def __init__(self, **kwargs) -> None:
            raise OSError("Invalid device [3]")

    import sys
    import types

    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        types.SimpleNamespace(InputStream=FailingInputStream),
    )
    monkeypatch.setattr("winwhisper.recorder.list_audio_input_devices", lambda: ())
    monkeypatch.setattr(
        "winwhisper.recorder.resolve_input_device",
        lambda name, host_api, index_hint, devices=None: ResolvedInputDevice(
            index=3, label="USB Mic [3]", fallback=False, reason=""
        ),
    )
    recorder = Recorder()
    recorder.set_audio_input_selection("USB Mic", "MME", 3)

    with pytest.raises(RecorderError) as caught:
        recorder.start_recording()
    error = caught.value
    assert str(error).endswith("(OSError).")
    assert "Invalid device [3]" not in str(error)
    assert error.details == (
        "OSError: Invalid device [3]; device=3; label=USB Mic [3]"
    )


def test_recorder_abort_error_still_closes_stream(monkeypatch):
    import sys
    import types

    class AbortFailingInputStream(FakeInputStream):
        def abort(self, ignore_errors=False) -> None:
            super().abort(ignore_errors=ignore_errors)
            raise OSError("CoreAudio abort failed")

    FakeInputStream.instances.clear()
    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        types.SimpleNamespace(
            InputStream=AbortFailingInputStream,
            _terminate=lambda: None,
            _initialize=lambda: None,
        ),
    )
    monkeypatch.setattr("winwhisper.recorder.list_audio_input_devices", lambda: ())
    monkeypatch.setattr(
        "winwhisper.recorder.resolve_input_device",
        lambda name, host_api, index_hint, devices=None: ResolvedInputDevice(
            index=None, label="System Default", fallback=False, reason=""
        ),
    )
    recorder = Recorder()
    recorder.start_recording()
    stream = FakeInputStream.instances[-1]

    with pytest.raises(RecorderError, match="Could not stop microphone recording"):
        recorder.stop_recording()

    assert stream.aborted is True
    assert stream.abort_ignore_errors is False
    assert stream.closed is True
    assert stream.close_ignore_errors is True


def test_recorder_omits_device_for_system_default(monkeypatch):
    install_fake_sounddevice(monkeypatch)
    monkeypatch.setattr("winwhisper.recorder.list_audio_input_devices", lambda: ())
    monkeypatch.setattr(
        "winwhisper.recorder.resolve_input_device",
        lambda name, host_api, index_hint, devices=None: ResolvedInputDevice(
            index=None, label="System Default", fallback=False, reason=""
        ),
    )
    recorder = Recorder()

    recorder.start_recording()

    assert "device" not in FakeInputStream.instances[-1].kwargs
    recorder.stop_recording().unlink()


def test_recorder_cannot_change_input_while_recording(monkeypatch):
    install_fake_sounddevice(monkeypatch)
    monkeypatch.setattr("winwhisper.recorder.list_audio_input_devices", lambda: ())
    monkeypatch.setattr(
        "winwhisper.recorder.resolve_input_device",
        lambda name, host_api, index_hint, devices=None: ResolvedInputDevice(
            index=None, label="System Default", fallback=False, reason=""
        ),
    )
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
    monkeypatch.setattr("winwhisper.recorder.list_audio_input_devices", lambda: ())
    monkeypatch.setattr(
        "winwhisper.recorder.resolve_input_device",
        lambda name, host_api, index_hint, devices=None: ResolvedInputDevice(
            index=None, label="System Default", fallback=False, reason=""
        ),
    )
    recorder = Recorder()

    with pytest.raises(RecorderError, match="Check microphone permissions"):
        recorder.start_recording()


def test_take_stats_peak_and_frames_survive_stop_recording(monkeypatch):
    import numpy as np

    install_fake_sounddevice(monkeypatch)
    monkeypatch.setattr("winwhisper.recorder.list_audio_input_devices", lambda: ())
    monkeypatch.setattr(
        "winwhisper.recorder.resolve_input_device",
        lambda name, host_api, index_hint, devices=None: ResolvedInputDevice(
            index=None, label="System Default", fallback=False, reason=""
        ),
    )
    recorder = Recorder()
    recorder.start_recording()
    stream = FakeInputStream.instances[-1]
    stream.kwargs["callback"](
        np.array([[16384], [-16384]], dtype="int16"),
        2,
        None,
        None,
    )
    stream.kwargs["callback"](
        np.zeros((2, 1), dtype="int16"),
        2,
        None,
        None,
    )

    path = recorder.stop_recording()
    assert path is not None
    path.unlink()

    stats = recorder.last_take_stats()
    assert stats is not None
    assert stats.frames == 4
    assert stats.peak == pytest.approx(0.5, abs=0.01)
    assert stats.device_label == "System Default"
    assert stats.first_block_ms is not None
    assert stats.first_block_ms >= 0.0
    assert stats.refresh_ms is not None
    assert stats.host_api == "default"
    assert recorder.current_level() == 0.0


def test_take_stats_reports_zero_frames_when_no_blocks(monkeypatch):
    install_fake_sounddevice(monkeypatch)
    monkeypatch.setattr("winwhisper.recorder.list_audio_input_devices", lambda: ())
    monkeypatch.setattr(
        "winwhisper.recorder.resolve_input_device",
        lambda name, host_api, index_hint, devices=None: ResolvedInputDevice(
            index=3, label="USB Mic [3]", fallback=False, reason=""
        ),
    )
    recorder = Recorder()
    recorder.start_recording()

    path = recorder.stop_recording()
    assert path is not None
    assert path.stat().st_size == 44
    path.unlink()

    stats = recorder.last_take_stats()
    assert stats is not None
    assert isinstance(stats, TakeStats)
    assert stats.frames == 0
    assert stats.peak == 0.0
    assert stats.first_block_ms is None
    assert stats.device_label == "USB Mic [3]"
    assert stats.refresh_ms is not None
    assert stats.host_api == "default"


def test_first_block_warning_when_no_audio_arrives(monkeypatch, caplog):
    import logging

    install_fake_sounddevice(monkeypatch)
    monkeypatch.setattr("winwhisper.recorder.list_audio_input_devices", lambda: ())
    monkeypatch.setattr(
        "winwhisper.recorder.resolve_input_device",
        lambda name, host_api, index_hint, devices=None: ResolvedInputDevice(
            index=2, label="PodMic [2]", fallback=False, reason=""
        ),
    )
    monkeypatch.setattr(
        "winwhisper.recorder.FIRST_BLOCK_WARN_SECONDS",
        0.01,
    )

    recorder = Recorder()
    with caplog.at_level(logging.WARNING, logger="winwhisper.recorder"):
        recorder.start_recording()
        # Let the first-block timer fire before stopping.
        import time as time_module

        time_module.sleep(0.05)
        path = recorder.stop_recording()
        assert path is not None
        path.unlink()

    assert any(
        "No audio blocks received within 500ms from PodMic [2]" in record.getMessage()
        for record in caplog.records
    )
    stats = recorder.last_take_stats()
    assert stats is not None
    assert stats.frames == 0
    assert stats.first_block_ms is None


def test_microphone_test_reports_live_level_without_writing_audio(monkeypatch):
    import numpy as np

    install_fake_sounddevice(monkeypatch)
    monkeypatch.setattr("winwhisper.recorder.list_audio_input_devices", lambda: ())
    monkeypatch.setattr(
        "winwhisper.recorder.resolve_input_device",
        lambda name, host_api, index_hint, devices=None: ResolvedInputDevice(
            index=2, label="USB Mic [2]", fallback=False, reason=""
        ),
    )
    microphone_test = MicrophoneTest(audio_input_device=2)
    microphone_test.set_audio_input_selection("USB Mic", "MME", 2)

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
    assert stream.aborted is True
    assert stream.abort_ignore_errors is False
    assert stream.closed is True
    assert stream.close_ignore_errors is True


def test_microphone_test_abort_error_still_closes_stream(monkeypatch):
    import sys
    import types

    class AbortFailingInputStream(FakeInputStream):
        def abort(self, ignore_errors=False) -> None:
            super().abort(ignore_errors=ignore_errors)
            raise OSError("CoreAudio abort failed")

    FakeInputStream.instances.clear()
    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        types.SimpleNamespace(
            InputStream=AbortFailingInputStream,
            _terminate=lambda: None,
            _initialize=lambda: None,
        ),
    )
    monkeypatch.setattr("winwhisper.recorder.list_audio_input_devices", lambda: ())
    monkeypatch.setattr(
        "winwhisper.recorder.resolve_input_device",
        lambda name, host_api, index_hint, devices=None: ResolvedInputDevice(
            index=None, label="System Default", fallback=False, reason=""
        ),
    )
    microphone_test = MicrophoneTest()
    microphone_test.start()
    stream = FakeInputStream.instances[-1]

    with pytest.raises(RecorderError, match="Could not stop microphone test"):
        microphone_test.stop()

    assert stream.aborted is True
    assert stream.abort_ignore_errors is False
    assert stream.closed is True
    assert stream.close_ignore_errors is True


def test_recorder_refresh_resolves_saved_name_to_new_index(monkeypatch):
    """After PortAudio re-init, a saved name must bind to the post-refresh index."""
    import sys
    import types

    import winwhisper.audio_inputs as audio_inputs

    FakeInputStream.instances.clear()
    generation = {"value": 0}

    def query_devices():
        if generation["value"] == 0:
            return [
                {"name": "Other", "max_input_channels": 1, "hostapi": 0},
                {
                    "name": "Desktop Microphone (RØDE PodMic",
                    "max_input_channels": 1,
                    "hostapi": 0,
                },
            ]
        return [
            {
                "name": "Desktop Microphone (RØDE PodMic",
                "max_input_channels": 1,
                "hostapi": 0,
            },
            {"name": "Beats Hands-Free", "max_input_channels": 1, "hostapi": 0},
        ]

    def terminate():
        return None

    def initialize():
        generation["value"] += 1

    sounddevice = types.SimpleNamespace(
        InputStream=FakeInputStream,
        _terminate=terminate,
        _initialize=initialize,
        query_devices=query_devices,
        query_hostapis=lambda index: {"name": "MME"},
        check_input_settings=lambda **kwargs: None,
    )
    monkeypatch.setitem(sys.modules, "sounddevice", sounddevice)
    monkeypatch.setattr(audio_inputs, "_use_native_macos_audio", lambda: False)
    monkeypatch.setattr(audio_inputs, "_device_supports_capture", lambda device: True)

    recorder = Recorder()
    recorder.set_audio_input_selection(
        "Desktop Microphone (RØDE PodMic",
        "MME",
        1,
    )
    recorder.start_recording()

    assert recorder.last_resolution is not None
    assert recorder.last_resolution.index == 0
    assert FakeInputStream.instances[-1].kwargs["device"] == 0
    stats_path = recorder.stop_recording()
    assert stats_path is not None
    stats_path.unlink()
    stats = recorder.last_take_stats()
    assert stats is not None
    assert stats.refresh_ms is not None
    assert stats.host_api == "MME"


def test_recorder_skips_refresh_while_another_stream_registered(monkeypatch):
    import winwhisper.audio_inputs as audio_inputs
    from winwhisper.audio_inputs import register_open_stream, unregister_open_stream

    install_fake_sounddevice(monkeypatch)
    refresh_calls: list[object] = []
    original = audio_inputs.refresh_audio_device_table

    def tracking_refresh():
        result = original()
        refresh_calls.append(result)
        return result

    monkeypatch.setattr(
        "winwhisper.recorder.refresh_audio_device_table",
        tracking_refresh,
    )
    monkeypatch.setattr("winwhisper.recorder.list_audio_input_devices", lambda: ())
    monkeypatch.setattr(
        "winwhisper.recorder.resolve_input_device",
        lambda name, host_api, index_hint, devices=None: ResolvedInputDevice(
            index=None, label="System Default", fallback=False, reason=""
        ),
    )

    register_open_stream()
    try:
        recorder = Recorder()
        recorder.start_recording()
        assert refresh_calls == [None]
        recorder.stop_recording().unlink()
    finally:
        unregister_open_stream()


def test_microphone_test_refreshes_and_registers_stream(monkeypatch):
    import winwhisper.audio_inputs as audio_inputs

    install_fake_sounddevice(monkeypatch)
    monkeypatch.setattr("winwhisper.recorder.list_audio_input_devices", lambda: ())
    monkeypatch.setattr(
        "winwhisper.recorder.resolve_input_device",
        lambda name, host_api, index_hint, devices=None: ResolvedInputDevice(
            index=None, label="System Default", fallback=False, reason=""
        ),
    )
    refresh_calls: list[object] = []
    monkeypatch.setattr(
        "winwhisper.recorder.refresh_audio_device_table",
        lambda: refresh_calls.append(1.0) or 1.0,
    )

    microphone_test = MicrophoneTest()
    microphone_test.start()
    assert refresh_calls == [1.0]
    with audio_inputs._open_stream_lock:
        assert audio_inputs._open_stream_count == 1
    microphone_test.stop()
    with audio_inputs._open_stream_lock:
        assert audio_inputs._open_stream_count == 0
