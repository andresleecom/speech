import dataclasses
import importlib
import sys

from winwhisper.config import Settings


def test_resolve_language_maps_supported_modes(monkeypatch, tmp_path):
    monkeypatch.setenv("WINWHISPER_APPDATA_DIR", str(tmp_path))
    transcriber = importlib.import_module("winwhisper.transcriber")

    assert transcriber.resolve_language("auto") is None
    assert transcriber.resolve_language("en") == "en"
    assert transcriber.resolve_language("es") == "es"
    assert transcriber.resolve_language("garbage") is None


def test_transcription_result_fields_match_plan():
    transcriber = importlib.import_module("winwhisper.transcriber")

    assert [field.name for field in dataclasses.fields(transcriber.TranscriptionResult)] == [
        "text",
        "language",
        "language_probability",
        "duration",
        "model_size",
        "device",
    ]


def test_transcriber_constructor_does_not_import_faster_whisper_or_load_model():
    sys.modules.pop("faster_whisper", None)
    sys.modules.pop("winwhisper.transcriber", None)

    transcriber = importlib.import_module("winwhisper.transcriber")

    assert "faster_whisper" not in sys.modules
    instance = transcriber.Transcriber(Settings())

    assert "faster_whisper" not in sys.modules
    assert instance._model is None
