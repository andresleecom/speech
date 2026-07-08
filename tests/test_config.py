import json

from winwhisper.config import DEFAULT_HOTKEYS, Settings, load_settings, save_settings


def test_defaults_when_no_file_exists(monkeypatch, tmp_path):
    monkeypatch.setenv("WINWHISPER_APPDATA_DIR", str(tmp_path))

    settings = load_settings()

    assert settings == Settings()
    assert settings.paste_mode == "auto"
    assert (tmp_path / "settings.json").exists()


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
