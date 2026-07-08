from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

DEFAULT_HOTKEYS = {
    "toggle_recording": "<ctrl>+<alt>+<space>",
    "force_english": "<ctrl>+<alt>+e",
    "force_spanish": "<ctrl>+<alt>+s",
}

PasteMode = Literal["auto", "clipboard_ctrl_v", "clipboard_ctrl_shift_v"]


class Settings(BaseModel):
    model_size: str = "small"
    device: str = "cpu"
    compute_type: str = "int8"
    language_mode: Literal["auto", "en", "es"] = "auto"
    cleanup_mode: Literal["none", "basic", "llm"] = "basic"
    paste_mode: PasteMode = "auto"
    delete_audio_after_transcription: bool = True
    hotkeys: dict[str, str] = Field(default_factory=lambda: DEFAULT_HOTKEYS.copy())

    model_config = ConfigDict(extra="ignore")


def app_data_dir() -> Path:
    override = os.getenv("WINWHISPER_APPDATA_DIR")
    if override:
        return Path(override)

    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata) / "WinWhisperDictate"

    return Path.home() / "AppData" / "Roaming" / "WinWhisperDictate"


def load_settings() -> Settings:
    _load_dotenv()
    settings_path = _settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    if not settings_path.exists():
        settings = Settings()
        save_settings(settings)
        return settings

    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("settings file must contain a JSON object")
        return Settings(**data)
    except (OSError, ValueError, json.JSONDecodeError, ValidationError) as exc:
        _log_warning(
            "Settings file is corrupt or invalid; using defaults (%s).",
            exc.__class__.__name__,
        )
        return Settings()


def save_settings(settings: Settings) -> None:
    settings_path = _settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(settings.model_dump(), indent=2) + "\n",
        encoding="utf-8",
    )


def _settings_path() -> Path:
    return app_data_dir() / "settings.json"


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        _log_warning("python-dotenv is not installed; skipping .env load.")
        return

    load_dotenv()


def _log_warning(message: str, *args: object) -> None:
    try:
        from .logger import get_logger

        get_logger(__name__).warning(message, *args)
    except Exception:
        pass
