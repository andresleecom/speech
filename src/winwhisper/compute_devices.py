"""Inference device and compute-type normalization for the Whisper backend.

CTranslate2, the runtime behind faster-whisper, only understands ``cpu``,
``cuda``, and ``auto``. The everyday word for the second one is "GPU", and
writing ``"device": "gpu"`` in settings.json used to fail deep inside model load
with ``ValueError: unsupported device gpu``, which broke every dictation instead
of just that setting. Aliases are resolved here, before the value reaches the
backend, and anything still unusable is caught by the CPU fallback in
``transcriber``.
"""
from __future__ import annotations

from typing import Final

CPU_DEVICE: Final = "cpu"
CUDA_DEVICE: Final = "cuda"
AUTO_DEVICE: Final = "auto"

SUPPORTED_DEVICES: Final = (CPU_DEVICE, CUDA_DEVICE, AUTO_DEVICE)

# Names a user can reasonably write for the same hardware. NVIDIA GPUs are the
# only accelerator CTranslate2 supports, so every GPU spelling maps to CUDA.
_DEVICE_ALIASES: Final = {
    CPU_DEVICE: CPU_DEVICE,
    CUDA_DEVICE: CUDA_DEVICE,
    AUTO_DEVICE: AUTO_DEVICE,
    "gpu": CUDA_DEVICE,
    "cuda:0": CUDA_DEVICE,
    "gpu:0": CUDA_DEVICE,
    "nvidia": CUDA_DEVICE,
}

# CTranslate2 quantization names, plus the two self-selecting values.
SUPPORTED_COMPUTE_TYPES: Final = (
    "default",
    "auto",
    "int8",
    "int8_float32",
    "int8_float16",
    "int8_bfloat16",
    "int16",
    "float16",
    "bfloat16",
    "float32",
)

DEFAULT_COMPUTE_TYPE: Final = "int8"

# The one device and compute-type pair that works on every machine Speech
# supports. Model load falls back to it rather than leaving the app unusable.
CPU_FALLBACK: Final = (CPU_DEVICE, DEFAULT_COMPUTE_TYPE)


def normalize_device(value: object) -> str:
    """Return a device name CTranslate2 accepts, resolving friendly aliases."""
    if value is None:
        return CPU_DEVICE
    if not isinstance(value, str):
        raise ValueError(_unsupported_device_message(value))

    device = _DEVICE_ALIASES.get(value.strip().casefold())
    if device is None:
        raise ValueError(_unsupported_device_message(value))
    return device


def normalize_compute_type(value: object) -> str:
    """Return a compute type CTranslate2 accepts."""
    if value is None:
        return DEFAULT_COMPUTE_TYPE
    if not isinstance(value, str):
        raise ValueError(_unsupported_compute_type_message(value))

    compute_type = value.strip().casefold()
    if compute_type not in SUPPORTED_COMPUTE_TYPES:
        raise ValueError(_unsupported_compute_type_message(value))
    return compute_type


def cuda_device_count() -> int:
    """Return the number of usable CUDA devices; 0 when CUDA is unavailable."""
    try:
        import ctranslate2

        return int(ctranslate2.get_cuda_device_count())
    except Exception:
        return 0


def _unsupported_device_message(value: object) -> str:
    return (
        f"Unsupported device {value!r}. Use 'cpu', 'cuda' for an NVIDIA GPU "
        "(also accepted as 'gpu'), or 'auto'."
    )


def _unsupported_compute_type_message(value: object) -> str:
    return (
        f"Unsupported compute type {value!r}. Use one of: "
        f"{', '.join(SUPPORTED_COMPUTE_TYPES)}."
    )
