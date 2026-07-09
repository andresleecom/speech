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


def test_build_hotwords_joins_and_strips_terms():
    transcriber = importlib.import_module("winwhisper.transcriber")

    assert transcriber.build_hotwords(["README", "  Claude Code ", ""]) == (
        "README, Claude Code"
    )
    assert transcriber.build_hotwords([]) is None
    assert transcriber.build_hotwords(None) is None
    assert transcriber.build_hotwords(["   ", ""]) is None


class _FakeModel:
    def __init__(self, captured: dict) -> None:
        self._captured = captured

    def transcribe(self, path, **kwargs):
        self._captured.update(kwargs)

        class Info:
            language = "en"
            language_probability = 1.0
            duration = 0.5

        return iter([]), Info()


def test_transcribe_passes_custom_vocabulary_as_hotwords(tmp_path):
    transcriber_mod = importlib.import_module("winwhisper.transcriber")
    settings = Settings(custom_vocabulary=["README", "winwhisper"])
    instance = transcriber_mod.Transcriber(settings)
    captured: dict = {}
    instance._model = _FakeModel(captured)
    audio = tmp_path / "take.wav"
    audio.write_bytes(b"")

    instance.transcribe(audio, "auto")

    assert captured["hotwords"] == "README, winwhisper"


def test_transcribe_passes_no_hotwords_without_vocabulary(tmp_path):
    transcriber_mod = importlib.import_module("winwhisper.transcriber")
    instance = transcriber_mod.Transcriber(Settings())
    captured: dict = {}
    instance._model = _FakeModel(captured)
    audio = tmp_path / "take.wav"
    audio.write_bytes(b"")

    instance.transcribe(audio, "auto")

    assert captured["hotwords"] is None


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
    assert instance.is_model_loaded() is False


def test_ensure_model_loaded_uses_cached_model():
    transcriber_mod = importlib.import_module("winwhisper.transcriber")
    instance = transcriber_mod.Transcriber(Settings())
    calls: list[str] = []
    sentinel = object()

    def fake_load(self):
        if self._model is not None:
            return self._model
        calls.append("load")
        self._model = sentinel
        return self._model

    original = transcriber_mod.Transcriber._load_model
    try:
        transcriber_mod.Transcriber._load_model = fake_load  # type: ignore[method-assign]
        instance.ensure_model_loaded()
        instance.ensure_model_loaded()
        assert instance.is_model_loaded() is True
        assert calls == ["load"]
        assert instance._model is sentinel
    finally:
        transcriber_mod.Transcriber._load_model = original  # type: ignore[method-assign]
