import importlib
import sys
import types

import pytest

from winwhisper.config import Settings


def _install_fake_faster_whisper(monkeypatch, failing_devices, encoder_failing_devices=()):
    """Stand in for faster-whisper.

    ``failing_devices`` fail at construction. ``encoder_failing_devices`` load
    fine and fail only once the segment generator is drained, which is how a
    missing cuBLAS actually behaves.
    """
    attempts: list[tuple[str, str]] = []

    class _Info:
        language = "en"
        language_probability = 1.0
        duration = 1.0

    class FakeWhisperModel:
        def __init__(self, model_size, device, compute_type):
            attempts.append((device, compute_type))
            if device in failing_devices:
                raise ValueError(f"unsupported device {device}")
            self.model_size = model_size
            self.device = device

        def transcribe(self, path, **kwargs):
            device = self.device

            def segments():
                if device in encoder_failing_devices:
                    raise RuntimeError(
                        "Library cublas64_12.dll is not found or cannot be loaded"
                    )
                yield types.SimpleNamespace(text=" hola mundo ")

            return segments(), _Info()

    module = types.ModuleType("faster_whisper")
    module.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    return attempts


def _transcriber():
    return importlib.import_module("winwhisper.transcriber")


def test_unusable_device_falls_back_to_cpu_and_notifies(monkeypatch):
    attempts = _install_fake_faster_whisper(monkeypatch, failing_devices={"cuda"})
    fallbacks: list[tuple[str, str]] = []
    instance = _transcriber().Transcriber(
        Settings(device="cuda", compute_type="float16"),
        lambda device, compute_type: fallbacks.append((device, compute_type)),
    )

    instance.ensure_model_loaded()

    assert attempts == [("cuda", "float16"), ("cpu", "int8")]
    assert fallbacks == [("cuda", "float16")]
    assert instance.device == "cpu"
    assert instance.is_model_loaded() is True


def test_unsupported_compute_type_on_cpu_also_falls_back(monkeypatch):
    attempts = _install_fake_faster_whisper(monkeypatch, failing_devices={"auto"})
    instance = _transcriber().Transcriber(Settings(device="auto", compute_type="bfloat16"))

    instance.ensure_model_loaded()

    assert attempts == [("auto", "bfloat16"), ("cpu", "int8")]
    assert instance.device == "cpu"


def test_cpu_baseline_failure_is_reported_rather_than_retried(monkeypatch):
    attempts = _install_fake_faster_whisper(monkeypatch, failing_devices={"cpu"})
    instance = _transcriber().Transcriber(Settings())

    with pytest.raises(ValueError, match="unsupported device cpu"):
        instance.ensure_model_loaded()

    assert attempts == [("cpu", "int8")]
    assert instance.is_model_loaded() is False


def test_working_device_never_reports_a_fallback(monkeypatch):
    attempts = _install_fake_faster_whisper(monkeypatch, failing_devices=set())
    fallbacks: list[tuple[str, str]] = []
    instance = _transcriber().Transcriber(
        Settings(device="gpu", compute_type="float16"),
        lambda device, compute_type: fallbacks.append((device, compute_type)),
    )

    instance.ensure_model_loaded()

    assert attempts == [("cuda", "float16")]
    assert fallbacks == []
    assert instance.device == "cuda"


def test_gpu_that_loads_but_cannot_encode_falls_back_mid_dictation(monkeypatch, tmp_path):
    attempts = _install_fake_faster_whisper(
        monkeypatch, failing_devices=set(), encoder_failing_devices={"cuda"}
    )
    fallbacks: list[tuple[str, str]] = []
    instance = _transcriber().Transcriber(
        Settings(device="cuda", compute_type="float16"),
        lambda device, compute_type: fallbacks.append((device, compute_type)),
    )
    audio = tmp_path / "take.wav"
    audio.write_bytes(b"")

    result = instance.transcribe(audio, "en")

    # The GPU model loads, so the load-time guard never sees it. The dictation
    # still has to succeed rather than raising at the user.
    assert attempts == [("cuda", "float16"), ("cpu", "int8")]
    assert fallbacks == [("cuda", "float16")]
    assert result.text == "hola mundo"
    assert result.device == "cpu"
    assert instance.device == "cpu"


def test_cpu_encoder_failure_is_reported_rather_than_retried(monkeypatch, tmp_path):
    attempts = _install_fake_faster_whisper(
        monkeypatch, failing_devices=set(), encoder_failing_devices={"cpu"}
    )
    instance = _transcriber().Transcriber(Settings())
    audio = tmp_path / "take.wav"
    audio.write_bytes(b"")

    with pytest.raises(RuntimeError, match="cublas"):
        instance.transcribe(audio, "en")

    assert attempts == [("cpu", "int8")]


def test_failing_fallback_notification_does_not_break_transcription(monkeypatch):
    _install_fake_faster_whisper(monkeypatch, failing_devices={"cuda"})

    def explode(device, compute_type):
        raise RuntimeError("tray is gone")

    instance = _transcriber().Transcriber(Settings(device="cuda"), explode)

    instance.ensure_model_loaded()

    assert instance.device == "cpu"
    assert instance.is_model_loaded() is True
