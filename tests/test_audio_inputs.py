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
    list_audio_input_devices,
    macos_audio_capture_device,
    normalize_audio_input_device,
)


@pytest.fixture(autouse=True)
def use_portaudio_device_discovery(monkeypatch):
    monkeypatch.setattr(audio_inputs, "_use_native_macos_audio", lambda: False)


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
    sounddevice = types.SimpleNamespace(
        query_devices=lambda: [
            {"name": "Speakers", "max_input_channels": 0},
            {"name": "Built-in Mic", "max_input_channels": 2},
            {"name": "USB Mic", "max_input_channels": 1},
        ]
    )
    monkeypatch.setitem(sys.modules, "sounddevice", sounddevice)

    assert list_audio_input_devices() == (
        AudioInputDevice(index=1, name="Built-in Mic", input_channels=2),
        AudioInputDevice(index=2, name="USB Mic", input_channels=1),
    )


def test_default_audio_input_device_uses_first_sounddevice_default(monkeypatch):
    sounddevice = types.SimpleNamespace(
        default=types.SimpleNamespace(device=(2, 4)),
    )
    monkeypatch.setitem(sys.modules, "sounddevice", sounddevice)

    assert default_audio_input_device() == 2


def test_audio_input_label_marks_unknown_saved_device():
    devices = (AudioInputDevice(index=1, name="Built-in Mic", input_channels=2),)

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
        AudioInputDevice(index=0, name="MacBook Microphone", input_channels=1),
        AudioInputDevice(index=1, name="USB Microphone", input_channels=1),
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
