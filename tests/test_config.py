import json

import pytest

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
    assert settings.language_favorites == ["en", "es", None]
    assert settings.custom_vocabulary == []
    assert (tmp_path / "settings.json").exists()


def test_default_force_language_hotkeys_avoid_altgr_and_macos_option():
    assert DEFAULT_HOTKEYS["force_english"] == "<ctrl>+<shift>+e"
    assert DEFAULT_HOTKEYS["force_spanish"] == "<ctrl>+<shift>+s"


def test_settings_accept_every_catalog_language_and_normalize_picker_labels():
    assert Settings(language_mode="French (fr)").language_mode == "fr"
    assert Settings(language_mode="yue").language_mode == "yue"

    with pytest.raises(ValueError, match="Unsupported language mode"):
        Settings(language_mode="not-a-language")


def test_settings_normalize_three_quick_language_favorites():
    settings = Settings(language_favorites=["French (fr)", "Japanese", "Not pinned"])

    assert settings.language_favorites == ["fr", "ja", None]

    with pytest.raises(ValueError, match="only once"):
        Settings(language_favorites=["fr", "French"])


def test_invalid_saved_language_falls_back_to_auto_without_losing_other_settings(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("WINWHISPER_APPDATA_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        json.dumps({"language_mode": "not-a-language", "model_size": "medium"}),
        encoding="utf-8",
    )

    settings = load_settings()

    assert settings.language_mode == "auto"
    assert settings.model_size == "medium"


def test_old_hotkey_settings_keep_english_and_spanish_as_favorites(monkeypatch, tmp_path):
    monkeypatch.setenv("WINWHISPER_APPDATA_DIR", str(tmp_path))
    hotkeys = {
        "toggle_recording": "<ctrl>+<alt>+<space>",
        "force_english": "<ctrl>+<shift>+e",
        "force_spanish": "<ctrl>+<shift>+s",
    }
    (tmp_path / "settings.json").write_text(
        json.dumps({"hotkeys": hotkeys}),
        encoding="utf-8",
    )

    settings = load_settings()

    assert settings.language_favorites == ["en", "es", None]
    assert settings.hotkeys == hotkeys


def test_custom_vocabulary_round_trips_through_settings_file(monkeypatch, tmp_path):
    monkeypatch.setenv("WINWHISPER_APPDATA_DIR", str(tmp_path))
    save_settings(Settings(custom_vocabulary=["README", "Claude Code"]))

    settings = load_settings()

    assert settings.custom_vocabulary == ["README", "Claude Code"]


def test_default_app_data_dir_uses_speech_name(monkeypatch, tmp_path):
    import sys

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("WINWHISPER_APPDATA_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))

    assert app_data_dir() == tmp_path / "Speech"
    assert legacy_app_data_dir() == tmp_path / "WinWhisperDictate"


def test_default_app_data_dir_on_macos(monkeypatch):
    import sys
    from pathlib import Path

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("WINWHISPER_APPDATA_DIR", raising=False)

    assert app_data_dir() == Path.home() / "Library" / "Application Support" / "Speech"


def test_default_app_data_dir_on_linux_respects_xdg(monkeypatch, tmp_path):
    import sys
    from pathlib import Path

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("WINWHISPER_APPDATA_DIR", raising=False)

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert app_data_dir() == tmp_path / "speech"

    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert app_data_dir() == Path.home() / ".config" / "speech"


def test_legacy_settings_are_migrated_to_speech_appdata(monkeypatch, tmp_path):
    import sys

    monkeypatch.setattr(sys, "platform", "win32")
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
