import sys
import types

import pytest

import winwhisper.audio_inputs as audio_inputs
from winwhisper.audio_inputs import (
    AudioInputDevice,
    AudioInputDeviceError,
    SYSTEM_DEFAULT_INPUT_LABEL,
    audio_input_device_label,
    default_audio_input_device,
    input_stream_extra_settings,
    list_audio_input_devices,
    macos_audio_capture_device,
    normalize_audio_input_device,
    resolve_input_device,
)


@pytest.fixture(autouse=True)
def use_portaudio_device_discovery(monkeypatch):
    monkeypatch.setattr(audio_inputs, "_use_native_macos_audio", lambda: False)


def _hostapis():
    return (
        {"name": "MME"},
        {"name": "Windows DirectSound"},
        {"name": "Windows WASAPI"},
        {"name": "Windows WDM-KS"},
    )


def test_audio_input_normalizer_accepts_default_and_nonnegative_indexes():
    assert normalize_audio_input_device(None) is None
    assert normalize_audio_input_device("System Default") is None
    assert normalize_audio_input_device("2") == 2
    assert normalize_audio_input_device(4) == 4


@pytest.mark.parametrize("value", [True, -1, "-1", "microphone", 1.0])
def test_audio_input_normalizer_rejects_invalid_values(value):
    with pytest.raises(ValueError, match="Audio input device"):
        normalize_audio_input_device(value)


def test_list_audio_input_devices_filters_non_input_devices(monkeypatch):
    hostapis = _hostapis()

    sounddevice = types.SimpleNamespace(
        query_devices=lambda: [
            {"name": "Speakers", "max_input_channels": 0, "hostapi": 0},
            {"name": "Built-in Mic", "max_input_channels": 2, "hostapi": 0},
            {"name": "USB Mic", "max_input_channels": 1, "hostapi": 1},
            {"name": "WDM Mic", "max_input_channels": 1, "hostapi": 3},
        ],
        query_hostapis=lambda index: hostapis[index],
    )
    monkeypatch.setitem(sys.modules, "sounddevice", sounddevice)

    assert list_audio_input_devices() == (
        AudioInputDevice(
            index=1, name="Built-in Mic", input_channels=2, host_api="MME"
        ),
        AudioInputDevice(
            index=2, name="USB Mic", input_channels=1, host_api="Windows DirectSound"
        ),
    )


def test_list_audio_input_devices_hides_wdm_ks_rows(monkeypatch):
    hostapis = _hostapis()
    sounddevice = types.SimpleNamespace(
        query_devices=lambda: [
            {"name": "PodMic", "max_input_channels": 1, "hostapi": 0},
            {"name": "PodMic", "max_input_channels": 1, "hostapi": 3},
        ],
        query_hostapis=lambda index: hostapis[index],
    )
    monkeypatch.setitem(sys.modules, "sounddevice", sounddevice)

    devices = list_audio_input_devices()
    assert len(devices) == 1
    assert devices[0].host_api == "MME"


def test_default_audio_input_device_uses_first_sounddevice_default(monkeypatch):
    sounddevice = types.SimpleNamespace(
        default=types.SimpleNamespace(device=(2, 4)),
    )
    monkeypatch.setitem(sys.modules, "sounddevice", sounddevice)

    assert default_audio_input_device() == 2


def test_audio_input_label_marks_unknown_saved_device():
    devices = (
        AudioInputDevice(
            index=1, name="Built-in Mic", input_channels=2, host_api="MME"
        ),
    )

    assert audio_input_device_label(None, devices) == SYSTEM_DEFAULT_INPUT_LABEL
    assert audio_input_device_label(1, devices) == "Built-in Mic [1]"
    assert audio_input_device_label(3, devices) == "Unavailable microphone [3]"


def test_device_listing_wraps_sounddevice_errors(monkeypatch):
    sounddevice = types.SimpleNamespace(
        query_devices=lambda: (_ for _ in ()).throw(RuntimeError("permission denied"))
    )
    monkeypatch.setitem(sys.modules, "sounddevice", sounddevice)

    with pytest.raises(AudioInputDeviceError, match="Could not list microphone"):
        list_audio_input_devices()


def test_resolve_input_device_system_default_is_not_a_fallback():
    resolved = resolve_input_device(None, None, None, ())
    assert resolved.index is None
    assert resolved.label == SYSTEM_DEFAULT_INPUT_LABEL
    assert resolved.fallback is False


def test_resolve_input_device_legacy_index_hint_matches_live_row():
    devices = (
        AudioInputDevice(
            index=2, name="PodMic", input_channels=1, host_api="MME"
        ),
    )
    resolved = resolve_input_device(None, None, 2, devices)
    assert resolved.index == 2
    assert resolved.label == "PodMic [2]"
    assert resolved.fallback is False
    assert resolved.reason == ""


def test_resolve_input_device_legacy_index_hint_falls_back_when_missing():
    devices = (
        AudioInputDevice(
            index=2, name="PodMic", input_channels=1, host_api="MME"
        ),
    )
    resolved = resolve_input_device(None, None, 3, devices)
    assert resolved.index is None
    assert resolved.label == SYSTEM_DEFAULT_INPUT_LABEL
    assert resolved.fallback is True
    assert resolved.reason == "Microphone [3] is unavailable"


def test_resolve_input_device_stale_hint_matches_by_name_and_host_api():
    devices = (
        AudioInputDevice(
            index=2,
            name="Desktop Microphone (RØDE PodMic",
            input_channels=1,
            host_api="MME",
        ),
        AudioInputDevice(
            index=12,
            name="Desktop Microphone (RØDE PodMic USB)",
            input_channels=1,
            host_api="Windows DirectSound",
        ),
    )

    resolved = resolve_input_device(
        "Desktop Microphone (RØDE PodMic",
        "MME",
        3,
        devices,
    )
    assert resolved.index == 2
    assert resolved.fallback is False
    assert resolved.label == "Desktop Microphone (RØDE PodMic [2]"


def test_resolve_input_device_falls_back_when_missing(monkeypatch):
    monkeypatch.setattr(
        audio_inputs,
        "_device_supports_capture",
        lambda device: False,
    )
    devices = (
        AudioInputDevice(
            index=1, name="Other Mic", input_channels=1, host_api="MME"
        ),
    )

    resolved = resolve_input_device("Missing Mic", "MME", 9, devices)
    assert resolved.index is None
    assert resolved.fallback is True
    assert resolved.label == SYSTEM_DEFAULT_INPUT_LABEL
    assert "Missing Mic" in resolved.reason


def test_resolve_input_device_same_name_uses_check_input_settings(monkeypatch):
    checked: list[int] = []

    def supports(device):
        checked.append(device.index)
        return device.host_api == "Windows WASAPI"

    monkeypatch.setattr(audio_inputs, "_device_supports_capture", supports)
    devices = (
        AudioInputDevice(
            index=2, name="PodMic", input_channels=1, host_api="MME"
        ),
        AudioInputDevice(
            index=27, name="PodMic", input_channels=1, host_api="Windows WASAPI"
        ),
    )

    resolved = resolve_input_device("PodMic", "Windows DirectSound", 3, devices)
    assert resolved.index == 27
    assert resolved.fallback is False
    assert checked == [2, 27]


def test_input_stream_extra_settings_only_for_wasapi(monkeypatch):
    class WasapiSettings:
        def __init__(self, auto_convert=False) -> None:
            self.auto_convert = auto_convert

    sounddevice = types.SimpleNamespace(WasapiSettings=WasapiSettings)
    monkeypatch.setitem(sys.modules, "sounddevice", sounddevice)

    assert input_stream_extra_settings("MME") == {}
    extras = input_stream_extra_settings("Windows WASAPI")
    assert set(extras) == {"extra_settings"}
    assert extras["extra_settings"].auto_convert is True


def test_macos_device_listing_and_default_use_avfoundation(monkeypatch):
    class Device:
        def __init__(self, name, unique_id):
            self._name = name
            self._unique_id = unique_id

        def localizedName(self):
            return self._name

        def uniqueID(self):
            return self._unique_id

    built_in = Device("MacBook Microphone", "built-in")
    usb = Device("USB Microphone", "usb")

    class CaptureDevice:
        @staticmethod
        def devicesWithMediaType_(media_type):
            assert media_type == "audio"
            return (built_in, usb)

        @staticmethod
        def defaultDeviceWithMediaType_(media_type):
            assert media_type == "audio"
            return usb

    avfoundation = types.SimpleNamespace(
        AVCaptureDevice=CaptureDevice,
        AVMediaTypeAudio="audio",
    )
    monkeypatch.setattr(audio_inputs, "_use_native_macos_audio", lambda: True)
    monkeypatch.setattr(audio_inputs, "_avfoundation", lambda: avfoundation)

    assert list_audio_input_devices() == (
        AudioInputDevice(
            index=0,
            name="MacBook Microphone",
            input_channels=1,
            host_api="built-in",
        ),
        AudioInputDevice(
            index=1,
            name="USB Microphone",
            input_channels=1,
            host_api="usb",
        ),
    )
    assert default_audio_input_device() == 1
    assert macos_audio_capture_device(None) is usb
    assert macos_audio_capture_device(0) is built_in


def test_macos_saved_device_reports_when_it_disappears(monkeypatch):
    class CaptureDevice:
        @staticmethod
        def devicesWithMediaType_(media_type):
            return ()

        @staticmethod
        def defaultDeviceWithMediaType_(media_type):
            return None

    avfoundation = types.SimpleNamespace(
        AVCaptureDevice=CaptureDevice,
        AVMediaTypeAudio="audio",
    )
    monkeypatch.setattr(audio_inputs, "_use_native_macos_audio", lambda: True)
    monkeypatch.setattr(audio_inputs, "_avfoundation", lambda: avfoundation)

    with pytest.raises(AudioInputDeviceError, match="no longer available"):
        macos_audio_capture_device(4)
