import sys
import threading
import types
from pathlib import Path

import pytest

import winwhisper.recorder_mac as recorder_mac
from winwhisper.recorder import RecorderError


def _bare_worker():
    worker = object.__new__(recorder_mac._CaptureWorker)
    worker._lock = threading.Lock()
    worker._logger = types.SimpleNamespace(exception=lambda *args, **kwargs: None)
    worker._native_capture = None
    worker._active = False
    worker._closed = False
    worker._level = 0.0
    worker._peak_level = 0.0
    worker._started_at = 0.0
    worker._max_duration_seconds = None
    worker._max_duration_was_reached = False
    worker._on_max_duration = None
    worker._meter_warning_logged = False
    return worker


class FakeSession:
    def __init__(self):
        self.running = False
        self.inputs = []
        self.outputs = []
        self.committed = False

    def init(self):
        return self

    def beginConfiguration(self):
        pass

    def commitConfiguration(self):
        self.committed = True

    def canAddInput_(self, device_input):
        return True

    def addInput_(self, device_input):
        self.inputs.append(device_input)

    def canAddOutput_(self, output):
        return True

    def addOutput_(self, output):
        self.outputs.append(output)

    def startRunning(self):
        self.running = True

    def stopRunning(self):
        self.running = False

    def isRunning(self):
        return self.running


class FakeOutput:
    def __init__(self, *, finish_on_stop=True):
        self.recording = False
        self.finish_on_stop = finish_on_stop
        self.delegate = None
        self.settings = None
        self.file_type = None
        self.output_path = None
        self.channel = types.SimpleNamespace(averagePowerLevel=lambda: -20.0)

    def init(self):
        return self

    def setAudioSettings_(self, settings):
        self.settings = settings

    def startRecordingToOutputFileURL_outputFileType_recordingDelegate_(
        self,
        output_path,
        file_type,
        delegate,
    ):
        self.output_path = Path(output_path)
        self.output_path.touch()
        self.file_type = file_type
        self.delegate = delegate
        self.recording = True

    def stopRecording(self):
        self.recording = False
        if self.finish_on_stop:
            self.delegate.finished_event.set()

    def isRecording(self):
        return self.recording

    def connections(self):
        return (
            types.SimpleNamespace(audioChannels=lambda: (self.channel,)),
        )


def _fake_avfoundation(session, output):
    class CaptureSession:
        @staticmethod
        def alloc():
            return session

    class AudioFileOutput:
        @staticmethod
        def alloc():
            return output

        @staticmethod
        def availableOutputFileTypes():
            return ("wave",)

    class DeviceInput:
        @staticmethod
        def deviceInputWithDevice_error_(device, error):
            return "device-input", None

    return types.SimpleNamespace(
        AVCaptureSession=CaptureSession,
        AVCaptureAudioFileOutput=AudioFileOutput,
        AVCaptureDeviceInput=DeviceInput,
        AVFileTypeWAVE="wave",
        AVFormatIDKey="format",
        AVSampleRateKey="sample-rate",
        AVNumberOfChannelsKey="channels",
        AVLinearPCMBitDepthKey="bit-depth",
        AVLinearPCMIsFloatKey="float",
        AVLinearPCMIsBigEndianKey="big-endian",
    )


def _install_fake_native_capture(monkeypatch, session, output, delegate):
    avfoundation = _fake_avfoundation(session, output)
    monkeypatch.setattr(
        recorder_mac,
        "_native_audio_frameworks",
        lambda: (
            avfoundation,
            types.SimpleNamespace(fileURLWithPath_=lambda value: value),
            1819304813,
        ),
    )
    monkeypatch.setattr(recorder_mac, "_ensure_microphone_permission", lambda avf: None)
    monkeypatch.setattr(
        recorder_mac,
        "macos_audio_capture_device",
        lambda selected: "microphone",
    )
    monkeypatch.setattr(recorder_mac, "_new_recording_delegate", lambda: delegate)


def test_native_capture_starts_meters_and_finalizes_wave(monkeypatch, tmp_path):
    session = FakeSession()
    output = FakeOutput()
    delegate = types.SimpleNamespace(
        finished_event=threading.Event(),
        error=None,
    )
    _install_fake_native_capture(monkeypatch, session, output, delegate)
    worker = _bare_worker()
    output_path = tmp_path / "recording.wav"

    worker._start_native_capture(output_path, None)
    worker._poll_capture()

    assert worker.is_active() is True
    assert session.running is True
    assert session.committed is True
    assert output.file_type == "wave"
    assert output.settings["sample-rate"] == 48_000.0
    assert output.settings["channels"] == 1
    assert worker.current_level() == pytest.approx(0.1)

    assert worker._stop_native_capture() == output_path
    assert worker.is_active() is False
    assert session.running is False


def test_native_capture_timeout_still_releases_session(monkeypatch, tmp_path):
    session = FakeSession()
    output = FakeOutput(finish_on_stop=False)
    delegate = types.SimpleNamespace(
        finished_event=threading.Event(),
        error=None,
    )
    _install_fake_native_capture(monkeypatch, session, output, delegate)
    monkeypatch.setattr(recorder_mac, "RECORDING_FINALIZE_TIMEOUT_SECONDS", 0.01)
    worker = _bare_worker()
    output_path = tmp_path / "recording.wav"
    worker._start_native_capture(output_path, None)

    with pytest.raises(RecorderError, match="finish writing"):
        worker._stop_native_capture()

    assert worker.is_active() is False
    assert session.running is False
    assert output_path.exists() is False


def test_permission_denied_has_actionable_recovery():
    capture_device = types.SimpleNamespace(
        authorizationStatusForMediaType_=lambda media_type: 2,
    )
    avfoundation = types.SimpleNamespace(
        AVCaptureDevice=capture_device,
        AVMediaTypeAudio="audio",
        AVAuthorizationStatusAuthorized=3,
        AVAuthorizationStatusDenied=2,
        AVAuthorizationStatusRestricted=1,
    )

    with pytest.raises(RecorderError, match="System Settings"):
        recorder_mac._ensure_microphone_permission(avfoundation)


def test_decibel_meter_conversion():
    assert recorder_mac._level_from_decibels(float("-inf")) == 0.0
    assert recorder_mac._level_from_decibels(-80.0) == 0.0
    assert recorder_mac._level_from_decibels(-20.0) == pytest.approx(0.1)
    assert recorder_mac._level_from_decibels(0.0) == 1.0


def test_main_thread_wait_pumps_cocoa_run_loop(monkeypatch):
    event = threading.Event()

    class RunLoop:
        calls = 0

        def runUntilDate_(self, date):
            self.calls += 1
            event.set()

    run_loop = RunLoop()
    foundation = types.SimpleNamespace(
        NSDate=types.SimpleNamespace(
            dateWithTimeIntervalSinceNow_=lambda seconds: seconds
        ),
        NSRunLoop=types.SimpleNamespace(currentRunLoop=lambda: run_loop),
        NSThread=types.SimpleNamespace(isMainThread=lambda: True),
    )
    monkeypatch.setitem(sys.modules, "Foundation", foundation)

    recorder_mac._wait_for_worker_event(event)

    assert run_loop.calls == 1
