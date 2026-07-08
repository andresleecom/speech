import json

from winwhisper.config import (
    DEFAULT_HOTKEYS,
    Settings,
    app_data_dir,
    legacy_app_data_dir,
    load_settings,
    save_settings,
)


def test_defaults_when_no_file_exists(monkeypatch, tmp_path):
    monkeypatch.setenv("WINWHISPER_APPDATA_DIR", str(tmp_path))

    settings = load_settings()

    assert settings == Settings()
    assert settings.paste_mode == "auto"
    assert settings.check_for_updates is True
    assert settings.last_update_check_at is None
    assert (tmp_path / "settings.json").exists()


def test_default_app_data_dir_uses_speech_name(monkeypatch, tmp_path):
    monkeypatch.delenv("WINWHISPER_APPDATA_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))

    assert app_data_dir() == tmp_path / "Speech"
    assert legacy_app_data_dir() == tmp_path / "WinWhisperDictate"


def test_legacy_settings_are_migrated_to_speech_appdata(monkeypatch, tmp_path):
    monkeypatch.delenv("WINWHISPER_APPDATA_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    legacy_dir = tmp_path / "WinWhisperDictate"
    legacy_dir.mkdir()
    (legacy_dir / "settings.json").write_text(
        json.dumps({"model_size": "medium"}),
        encoding="utf-8",
    )

    settings = load_settings()

    assert settings.model_size == "medium"
    assert (tmp_path / "Speech" / "settings.json").exists()


def test_save_load_round_trip(monkeypatch, tmp_path):
    monkeypatch.setenv("WINWHISPER_APPDATA_DIR", str(tmp_path))
    settings = Settings(
        model_size="medium",
        device="cuda",
        compute_type="float16",
        language_mode="en",
        cleanup_mode="none",
        paste_mode="clipboard_ctrl_v",
        delete_audio_after_transcription=False,
        check_for_updates=False,
        last_update_check_at=1_780_000_000.0,
        hotkeys={**DEFAULT_HOTKEYS, "toggle_recording": "<ctrl>+<shift>+space"},
    )

    save_settings(settings)

    assert load_settings() == settings


def test_ctrl_shift_v_paste_mode_is_valid(monkeypatch, tmp_path):
    monkeypatch.setenv("WINWHISPER_APPDATA_DIR", str(tmp_path))
    settings = Settings(paste_mode="clipboard_ctrl_shift_v")

    save_settings(settings)

    assert load_settings().paste_mode == "clipboard_ctrl_shift_v"


def test_unknown_keys_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("WINWHISPER_APPDATA_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        json.dumps({"model_size": "medium", "unknown": "ignored"}),
        encoding="utf-8",
    )

    settings = load_settings()

    assert settings.model_size == "medium"
    assert not hasattr(settings, "unknown")


def test_corrupt_json_falls_back_to_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("WINWHISPER_APPDATA_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text("{not json", encoding="utf-8")

    assert load_settings() == Settings()
    assert not (tmp_path / "settings.json").exists()
    assert (tmp_path / "settings.json.corrupt").exists()


def test_save_settings_is_atomic(monkeypatch, tmp_path):
    monkeypatch.setenv("WINWHISPER_APPDATA_DIR", str(tmp_path))
    settings = Settings(model_size="medium")

    save_settings(settings)

    assert (tmp_path / "settings.json").exists()
    assert not (tmp_path / "settings.json.tmp").exists()
    assert load_settings().model_size == "medium"
