import pytest

from winwhisper.compute_devices import (
    CPU_FALLBACK,
    normalize_compute_type,
    normalize_device,
)


def test_gpu_spellings_resolve_to_cuda():
    assert normalize_device("gpu") == "cuda"
    assert normalize_device("GPU") == "cuda"
    assert normalize_device(" Nvidia ") == "cuda"
    assert normalize_device("cuda:0") == "cuda"


def test_supported_devices_pass_through():
    assert normalize_device("cpu") == "cpu"
    assert normalize_device("cuda") == "cuda"
    assert normalize_device("auto") == "auto"
    assert normalize_device(None) == "cpu"


def test_unsupported_devices_name_the_valid_choices():
    for value in ("mps", "metal", "rocm", "", 1):
        with pytest.raises(ValueError, match="Unsupported device"):
            normalize_device(value)


def test_compute_types_are_validated_against_ctranslate2_names():
    assert normalize_compute_type("FLOAT16") == "float16"
    assert normalize_compute_type(" int8_float16 ") == "int8_float16"
    assert normalize_compute_type("auto") == "auto"
    assert normalize_compute_type(None) == "int8"

    with pytest.raises(ValueError, match="Unsupported compute type"):
        normalize_compute_type("float8")


def test_cpu_fallback_is_the_universally_available_pair():
    assert CPU_FALLBACK == ("cpu", "int8")
