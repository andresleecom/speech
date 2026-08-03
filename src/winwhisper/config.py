from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .audio_inputs import normalize_audio_input_device
from .branding import APP_NAME, LEGACY_APP_NAME
from .compute_devices import (
    CPU_DEVICE,
    DEFAULT_COMPUTE_TYPE,
    normalize_compute_type,
    normalize_device,
)
from .hotkey_actions import DEFAULT_HOTKEYS
from .languages import (
    AUTO_LANGUAGE_MODE,
    DEFAULT_LANGUAGE_FAVORITES,
    normalize_language_favorites,
    normalize_language_mode,
)

PasteMode = Literal["auto", "clipboard_ctrl_v", "clipboard_ctrl_shift_v"]

_SAVE_LOCK = threading.Lock()


class Settings(BaseModel):
    model_size: str = "small"
    device: str = CPU_DEVICE
    compute_type: str = DEFAULT_COMPUTE_TYPE
    audio_input_device: int | None = None
    language_mode: str = AUTO_LANGUAGE_MODE
    language_favorites: list[str | None] = Field(
        default_factory=lambda: list(DEFAULT_LANGUAGE_FAVORITES)
    )
    cleanup_mode: Literal["none", "basic", "llm"] = "basic"
    paste_mode: PasteMode = "auto"
    delete_audio_after_transcription: bool = True
    check_for_updates: bool = True
    last_update_check_at: float | None = None
    hotkeys: dict[str, str] = Field(default_factory=lambda: DEFAULT_HOTKEYS.copy())
    # Names and terms you use often (e.g. product names, people, jargon).
    # They bias transcription and cleanup toward these exact spellings.
    custom_vocabulary: list[str] = Field(default_factory=list)
    # Hands-free mode: say any wake phrase to start dictation, the stop
    # phrase (or a few seconds of silence) to finish and paste.
    wake_word_enabled: bool = False
    wake_phrases: list[str] = Field(
        default_factory=lambda: ["hey speech", "oye speech"]
    )
    stop_phrase: str = "stop"
    wake_silence_timeout_seconds: float = 3.0
    # tiny is the safe default for CPU-only machines. On a GPU, base/small
    # hear accented or code-switched phrases much better.
    wake_model_size: str = "tiny"

    model_config = ConfigDict(extra="ignore")

    @field_validator("language_mode", mode="before")
    @classmethod
    def validate_language_mode(cls, value: object) -> str:
        normalized = normalize_language_mode(value)
        if normalized is None:
            raise ValueError(f"Unsupported language mode: {value!r}")
        return normalized

    @field_validator("device", mode="before")
    @classmethod
    def validate_device(cls, value: object) -> str:
        return normalize_device(value)

    @field_validator("compute_type", mode="before")
    @classmethod
    def validate_compute_type(cls, value: object) -> str:
        return normalize_compute_type(value)

    @field_validator("audio_input_device", mode="before")
    @classmethod
    def validate_audio_input_device(cls, value: object) -> int | None:
        return normalize_audio_input_device(value)

    @field_validator("language_favorites", mode="before")
    @classmethod
    def validate_language_favorites(cls, value: object) -> list[str | None]:
        return list(normalize_language_favorites(value))

    @field_validator("wake_phrases", mode="before")
    @classmethod
    def validate_wake_phrases(cls, value: object) -> list[str]:
        from .wake_word import normalize_phrase

        raw = [value] if isinstance(value, str) else list(value or ())
        phrases = [phrase for phrase in (normalize_phrase(item) for item in raw) if phrase]
        if not phrases:
            raise ValueError(f"At least one wake phrase is required: {value!r}")
        return phrases

    @field_validator("stop_phrase", mode="before")
    @classmethod
    def validate_phrase(cls, value: object) -> str:
        from .wake_word import normalize_phrase

        normalized = normalize_phrase(value)
        if not normalized:
            raise ValueError(f"Phrase must contain at least one word: {value!r}")
        return normalized

    @field_validator("wake_model_size", mode="before")
    @classmethod
    def validate_wake_model_size(cls, value: object) -> str:
        size = str(value).strip()
        if not size:
            raise ValueError("wake_model_size must not be empty")
        return size

    @field_validator("wake_silence_timeout_seconds", mode="before")
    @classmethod
    def validate_silence_timeout(cls, value: object) -> float:
        seconds = float(value)  # raises for non-numeric input
        return min(30.0, max(1.0, seconds))


def app_data_dir() -> Path:
    override = os.getenv("WINWHISPER_APPDATA_DIR")
    if override:
        return Path(override)

    return _default_app_data_dir(APP_NAME)


def legacy_app_data_dir() -> Path:
    return _default_app_data_dir(LEGACY_APP_NAME)


def _default_app_data_dir(name: str) -> Path:
    if sys.platform == "win32":
        appdata = os.getenv("APPDATA")
        if appdata:
            return Path(appdata) / name
        return Path.home() / "AppData" / "Roaming" / name

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / name

    xdg_config = os.getenv("XDG_CONFIG_HOME")
    base = Path(xdg_config) if xdg_config else Path.home() / ".config"
    return base / name.lower()


def load_settings() -> Settings:
    _load_dotenv()
    settings_path = _settings_path()
    _migrate_legacy_settings(settings_path)
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    if not settings_path.exists():
        settings = Settings()
        save_settings(settings)
        return settings

    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("settings file must contain a JSON object")
        _migrate_language_mode(data)
        _migrate_language_favorites(data)
        _migrate_audio_input_device(data)
        _migrate_device(data)
        _migrate_compute_type(data)
        _migrate_wake_phrase(data)
        return Settings(**data)
    except (OSError, ValueError, json.JSONDecodeError, ValidationError) as exc:
        _log_warning(
            "Settings file is corrupt or invalid; using defaults (%s).",
            exc.__class__.__name__,
        )
        _quarantine_corrupt_settings(settings_path)
        return Settings()


def save_settings(settings: Settings) -> None:
    settings_path = _settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(settings.model_dump(), indent=2) + "\n"
    temp_path = settings_path.with_name(settings_path.name + ".tmp")

    with _SAVE_LOCK:
        temp_path.write_text(payload, encoding="utf-8")
        os.replace(temp_path, settings_path)


def _quarantine_corrupt_settings(settings_path: Path) -> None:
    try:
        if not settings_path.exists():
            return
        corrupt_path = settings_path.with_name(settings_path.name + ".corrupt")
        os.replace(settings_path, corrupt_path)
        _log_warning("Corrupt settings moved to %s.", corrupt_path.name)
    except OSError:
        pass


def _settings_path() -> Path:
    return app_data_dir() / "settings.json"


def _legacy_settings_path() -> Path:
    return legacy_app_data_dir() / "settings.json"


def _migrate_legacy_settings(settings_path: Path) -> None:
    if os.getenv("WINWHISPER_APPDATA_DIR"):
        return
    if settings_path.exists():
        return

    legacy_settings_path = _legacy_settings_path()
    if not legacy_settings_path.exists():
        return

    try:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        payload = legacy_settings_path.read_text(encoding="utf-8")
        temp_path = settings_path.with_name(settings_path.name + ".tmp")
        with _SAVE_LOCK:
            temp_path.write_text(payload, encoding="utf-8")
            os.replace(temp_path, settings_path)
    except OSError as exc:
        _log_warning(
            "Legacy settings could not be migrated (%s).",
            exc.__class__.__name__,
        )


def _migrate_language_mode(data: dict[str, object]) -> None:
    """Keep a hand-edited obsolete language value from discarding all settings."""
    if "language_mode" not in data:
        return
    normalized = normalize_language_mode(data["language_mode"])
    if normalized is None:
        _log_warning(
            "Unknown language mode %r; using automatic detection.",
            data["language_mode"],
        )
        data["language_mode"] = AUTO_LANGUAGE_MODE
        return
    data["language_mode"] = normalized


def _migrate_language_favorites(data: dict[str, object]) -> None:
    if "language_favorites" not in data:
        return
    try:
        data["language_favorites"] = list(
            normalize_language_favorites(data["language_favorites"])
        )
    except ValueError:
        _log_warning("Invalid language favorites; restoring default favorites.")
        data["language_favorites"] = list(DEFAULT_LANGUAGE_FAVORITES)


def _migrate_audio_input_device(data: dict[str, object]) -> None:
    if "audio_input_device" not in data:
        return
    try:
        data["audio_input_device"] = normalize_audio_input_device(
            data["audio_input_device"]
        )
    except ValueError:
        _log_warning("Invalid audio input device; restoring System Default.")
        data["audio_input_device"] = None


def _migrate_device(data: dict[str, object]) -> None:
    """Keep a hand-edited unusable device from discarding all settings."""
    if "device" not in data:
        return
    try:
        data["device"] = normalize_device(data["device"])
    except ValueError:
        _log_warning(
            "Unsupported device %r; using the CPU. Set 'cuda' (or 'gpu') for an "
            "NVIDIA GPU.",
            data["device"],
        )
        data["device"] = CPU_DEVICE


def _migrate_compute_type(data: dict[str, object]) -> None:
    if "compute_type" not in data:
        return
    try:
        data["compute_type"] = normalize_compute_type(data["compute_type"])
    except ValueError:
        _log_warning(
            "Unsupported compute type %r; using %s.",
            data["compute_type"],
            DEFAULT_COMPUTE_TYPE,
        )
        data["compute_type"] = DEFAULT_COMPUTE_TYPE


def _migrate_wake_phrase(data: dict[str, object]) -> None:
    """Move the old single wake_phrase key into the wake_phrases list."""
    if "wake_phrase" not in data or "wake_phrases" in data:
        return
    old_phrase = data.pop("wake_phrase")
    if isinstance(old_phrase, str) and old_phrase.strip():
        data["wake_phrases"] = [old_phrase]


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
