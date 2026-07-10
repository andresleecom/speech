import sys
import types

import pytest

from winwhisper.audio_inputs import (
    AudioInputDevice,
    AudioInputDeviceError,
    SYSTEM_DEFAULT_INPUT_LABEL,
    audio_input_device_label,
    default_audio_input_device,
    list_audio_input_devices,
    normalize_audio_input_device,
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
