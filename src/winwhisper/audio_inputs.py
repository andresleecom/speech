"""Input-device discovery and settings normalization for microphone capture."""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from typing import Any, Final


SYSTEM_DEFAULT_INPUT_LABEL: Final = "System Default"
_SYSTEM_DEFAULT_ALIASES: Final = frozenset(
    {"", "default", "systemdefault", "system", "none", "auto"}
)


class AudioInputDeviceError(RuntimeError):
    """Raised when available microphone devices cannot be inspected."""


@dataclass(frozen=True, slots=True)
class AudioInputDevice:
    index: int
    name: str
    input_channels: int

    @property
    def choice_label(self) -> str:
        return f"{self.name} [{self.index}]"


def normalize_audio_input_device(value: object) -> int | None:
    """Return a non-negative device index, or ``None`` for the system default."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(
            "Audio input device must be a non-negative device number or System Default."
        )
    if isinstance(value, str):
        stripped = value.strip()
        normalized = re.sub(r"[^a-z0-9]+", "", stripped.casefold())
        if normalized in _SYSTEM_DEFAULT_ALIASES:
            return None
        if not stripped.isdecimal():
            raise ValueError(
                "Audio input device must be a non-negative device number or System Default."
            )
        value = int(stripped)
    if not isinstance(value, int) or value < 0:
        raise ValueError(
            "Audio input device must be a non-negative device number or System Default."
        )
    return value


def list_audio_input_devices() -> tuple[AudioInputDevice, ...]:
    """List every audio device that can capture at least one input channel."""
    if _use_native_macos_audio():
        return _list_macos_audio_input_devices()

    sounddevice = _sounddevice()
    try:
        raw_devices = sounddevice.query_devices()
    except Exception as exc:
        raise AudioInputDeviceError(
            "Could not list microphone devices. Check microphone permissions and try again."
        ) from exc

    devices: list[AudioInputDevice] = []
    for index, device in enumerate(raw_devices):
        channels = _device_input_channels(device)
        if channels <= 0:
            continue
        name = str(_device_value(device, "name", "Unknown microphone")).strip()
        devices.append(
            AudioInputDevice(
                index=index,
                name=name or "Unknown microphone",
                input_channels=channels,
            )
        )
    return tuple(devices)


def default_audio_input_device() -> int | None:
    """Return the current system-default input index."""
    if _use_native_macos_audio():
        return _default_macos_audio_input_device()

    sounddevice = _sounddevice()
    try:
        default_device = sounddevice.default.device
    except Exception as exc:
        raise AudioInputDeviceError(
            "Could not inspect the system-default microphone."
        ) from exc

    if isinstance(default_device, (tuple, list)):
        default_device = default_device[0] if default_device else None
    try:
        return normalize_audio_input_device(default_device)
    except ValueError:
        return None


def audio_input_device_label(
    selected_device: object,
    devices: tuple[AudioInputDevice, ...] | None = None,
) -> str:
    """Return a stable human-readable label for a saved input selection."""
    normalized = normalize_audio_input_device(selected_device)
    if normalized is None:
        return SYSTEM_DEFAULT_INPUT_LABEL
    if devices is not None:
        for device in devices:
            if device.index == normalized:
                return device.choice_label
    return f"Unavailable microphone [{normalized}]"


def _sounddevice() -> Any:
    try:
        import sounddevice
    except ImportError as exc:
        raise AudioInputDeviceError(
            "sounddevice is not installed; microphone input is unavailable."
        ) from exc
    return sounddevice


def macos_audio_capture_device(selected_device: object) -> Any:
    """Resolve a saved macOS device index to an AVFoundation capture device."""
    normalized = normalize_audio_input_device(selected_device)
    avfoundation = _avfoundation()
    try:
        if normalized is None:
            device = avfoundation.AVCaptureDevice.defaultDeviceWithMediaType_(
                avfoundation.AVMediaTypeAudio
            )
        else:
            devices = _macos_capture_devices(avfoundation)
            device = devices[normalized] if normalized < len(devices) else None
    except Exception as exc:
        raise AudioInputDeviceError(
            "Could not inspect macOS microphone devices."
        ) from exc

    if device is None:
        if normalized is None:
            raise AudioInputDeviceError(
                "No system-default microphone is available. Choose an input in "
                "System Settings > Sound."
            )
        raise AudioInputDeviceError(
            "The selected microphone is no longer available. Choose System Default "
            "or another device."
        )
    return device


def _use_native_macos_audio() -> bool:
    return sys.platform == "darwin"


def _list_macos_audio_input_devices() -> tuple[AudioInputDevice, ...]:
    avfoundation = _avfoundation()
    try:
        devices = _macos_capture_devices(avfoundation)
        return tuple(
            AudioInputDevice(
                index=index,
                name=str(device.localizedName()).strip() or "Unknown microphone",
                input_channels=1,
            )
            for index, device in enumerate(devices)
        )
    except Exception as exc:
        raise AudioInputDeviceError(
            "Could not list microphone devices. Check microphone permissions and try again."
        ) from exc


def _default_macos_audio_input_device() -> int | None:
    avfoundation = _avfoundation()
    try:
        default_device = avfoundation.AVCaptureDevice.defaultDeviceWithMediaType_(
            avfoundation.AVMediaTypeAudio
        )
        if default_device is None:
            return None
        default_id = str(default_device.uniqueID())
        for index, device in enumerate(_macos_capture_devices(avfoundation)):
            if str(device.uniqueID()) == default_id:
                return index
    except Exception as exc:
        raise AudioInputDeviceError(
            "Could not inspect the system-default microphone."
        ) from exc
    return None


def _avfoundation() -> Any:
    try:
        import AVFoundation
    except ImportError as exc:
        raise AudioInputDeviceError(
            "AVFoundation support is not installed; microphone input is unavailable."
        ) from exc
    return AVFoundation


def _macos_capture_devices(avfoundation: Any) -> tuple[Any, ...]:
    # devicesWithMediaType_ remains available on the oldest macOS release that
    # Speech supports, unlike newer discovery-session device-type constants.
    return tuple(
        avfoundation.AVCaptureDevice.devicesWithMediaType_(
            avfoundation.AVMediaTypeAudio
        )
    )


def _device_value(device: Any, key: str, fallback: object) -> object:
    getter = getattr(device, "get", None)
    if callable(getter):
        return getter(key, fallback)
    return fallback


def _device_input_channels(device: Any) -> int:
    try:
        return max(0, int(_device_value(device, "max_input_channels", 0)))
    except (TypeError, ValueError):
        return 0
