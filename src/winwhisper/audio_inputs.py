"""Input-device discovery and settings normalization for microphone capture."""
from __future__ import annotations

import logging
import re
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Final


SYSTEM_DEFAULT_INPUT_LABEL: Final = "System Default"
_SYSTEM_DEFAULT_ALIASES: Final = frozenset(
    {"", "default", "systemdefault", "system", "none", "auto"}
)
_SKIPPED_HOST_APIS: Final = frozenset({"Windows WDM-KS"})
_WASAPI_HOST_API: Final = "Windows WASAPI"
_CAPTURE_SAMPLE_RATE: Final = 16_000
_CAPTURE_CHANNELS: Final = 1
_CAPTURE_DTYPE: Final = "int16"

# Use stdlib logging here: importing winwhisper.logger pulls in config, which
# imports this module, and a package-logger import would cycle at load time.
_logger = logging.getLogger(__name__)
_open_stream_lock = threading.Lock()
_open_stream_count = 0


def register_open_stream() -> None:
    """Mark that this process holds an open PortAudio stream."""
    global _open_stream_count
    with _open_stream_lock:
        _open_stream_count += 1


def unregister_open_stream() -> None:
    """Mark that a PortAudio stream in this process has been closed."""
    global _open_stream_count
    with _open_stream_lock:
        if _open_stream_count > 0:
            _open_stream_count -= 1


def refresh_audio_device_table() -> float | None:
    """Re-run PortAudio init so the device table matches current hardware.

    Returns elapsed milliseconds on success, or ``None`` when skipped (macOS,
    any open stream in-process) or when terminate/initialize raises.
    Must never run while a PortAudio stream is open in this process.
    """
    if _use_native_macos_audio():
        return None

    with _open_stream_lock:
        if _open_stream_count > 0:
            _logger.debug(
                "Skipping audio device table refresh; %s open stream(s) in process.",
                _open_stream_count,
            )
            return None
        try:
            sounddevice = _sounddevice()
            started = time.perf_counter()
            sounddevice._terminate()
            sounddevice._initialize()
            return (time.perf_counter() - started) * 1000.0
        except Exception:
            _logger.warning(
                "Could not refresh the PortAudio device table.",
                exc_info=True,
            )
            return None


class AudioInputDeviceError(RuntimeError):
    """Raised when available microphone devices cannot be inspected."""


@dataclass(frozen=True, slots=True)
class AudioInputDevice:
    index: int
    name: str
    input_channels: int
    host_api: str = ""

    @property
    def choice_label(self) -> str:
        return f"{self.name} [{self.index}]"


@dataclass(frozen=True, slots=True)
class ResolvedInputDevice:
    index: int | None
    label: str
    fallback: bool
    reason: str


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
        host_api = _sounddevice_host_api_name(sounddevice, device)
        if host_api in _SKIPPED_HOST_APIS:
            continue
        name = str(_device_value(device, "name", "Unknown microphone")).strip()
        devices.append(
            AudioInputDevice(
                index=index,
                name=name or "Unknown microphone",
                input_channels=channels,
                host_api=host_api,
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


def resolve_input_device(
    name: str | None,
    host_api: str | None,
    index_hint: int | None,
    devices: tuple[AudioInputDevice, ...] | None = None,
) -> ResolvedInputDevice:
    """Resolve a saved microphone identity to a live PortAudio index.

    ``name is None`` with no ``index_hint`` is an intentional System Default choice.
    ``name is None`` with a live ``index_hint`` is a legacy index-only selection.
    When the saved device is missing, returns System Default with ``fallback=True``.
    """
    if name is None:
        if index_hint is None:
            return ResolvedInputDevice(
                index=None,
                label=SYSTEM_DEFAULT_INPUT_LABEL,
                fallback=False,
                reason="",
            )
        if devices is None:
            devices = list_audio_input_devices()
        for device in devices:
            if device.index == index_hint:
                return ResolvedInputDevice(
                    index=device.index,
                    label=device.choice_label,
                    fallback=False,
                    reason="",
                )
        return ResolvedInputDevice(
            index=None,
            label=SYSTEM_DEFAULT_INPUT_LABEL,
            fallback=True,
            reason=f"Microphone [{index_hint}] is unavailable",
        )

    if devices is None:
        devices = list_audio_input_devices()

    for device in devices:
        if device.name == name and device.host_api == (host_api or ""):
            return ResolvedInputDevice(
                index=device.index,
                label=device.choice_label,
                fallback=False,
                reason="",
            )

    same_name = [device for device in devices if device.name == name]
    if index_hint is not None:
        same_name.sort(key=lambda device: (0 if device.index == index_hint else 1, device.index))
    for device in same_name:
        if _device_supports_capture(device):
            return ResolvedInputDevice(
                index=device.index,
                label=device.choice_label,
                fallback=False,
                reason="",
            )

    saved_label = name if not host_api else f"{name} ({host_api})"
    return ResolvedInputDevice(
        index=None,
        label=SYSTEM_DEFAULT_INPUT_LABEL,
        fallback=True,
        reason=f"{saved_label} is unavailable",
    )


def input_stream_extra_settings(host_api: str | None) -> dict[str, Any]:
    """Return InputStream kwargs needed for the given host API, if any."""
    if host_api != _WASAPI_HOST_API:
        return {}
    sounddevice = _sounddevice()
    return {"extra_settings": sounddevice.WasapiSettings(auto_convert=True)}


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
                host_api=str(device.uniqueID()),
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


def _sounddevice_host_api_name(sounddevice: Any, device: Any) -> str:
    try:
        hostapi_index = int(_device_value(device, "hostapi", -1))
        info = sounddevice.query_hostapis(hostapi_index)
        name = _device_value(info, "name", "")
        return str(name).strip() or "Unknown"
    except Exception:
        return "Unknown"


def _device_supports_capture(device: AudioInputDevice) -> bool:
    if _use_native_macos_audio():
        return True
    try:
        sounddevice = _sounddevice()
        options: dict[str, Any] = {
            "device": device.index,
            "samplerate": _CAPTURE_SAMPLE_RATE,
            "channels": _CAPTURE_CHANNELS,
            "dtype": _CAPTURE_DTYPE,
        }
        options.update(input_stream_extra_settings(device.host_api))
        sounddevice.check_input_settings(**options)
        return True
    except Exception:
        return False
