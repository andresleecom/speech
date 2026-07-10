from __future__ import annotations

from dataclasses import dataclass

from .languages import (
    DEFAULT_LANGUAGE_FAVORITES,
    language_name,
    normalize_language_favorites,
)


@dataclass(frozen=True)
class HotkeyAction:
    setting_key: str
    dispatch_action: str
    label: str
    default_combo: str
    windows_suggestions: tuple[str, ...]
    macos_suggestions: tuple[str, ...]
    language_favorite_index: int | None = None

    def suggestions(self, platform: str) -> tuple[str, ...]:
        if platform == "darwin":
            return self.macos_suggestions
        return self.windows_suggestions

    def label_for_favorites(self, favorites: object) -> str:
        if self.language_favorite_index is None:
            return self.label
        try:
            normalized_favorites = normalize_language_favorites(favorites)
        except ValueError:
            normalized_favorites = DEFAULT_LANGUAGE_FAVORITES
        language = normalized_favorites[self.language_favorite_index]
        if language is None:
            return f"Quick language {self.language_favorite_index + 1} (not set)"
        return f"Dictate in {language_name(language)}"


_TOGGLE_SUGGESTIONS = (
    "<ctrl>+<alt>+<space>",
    "<ctrl>+<shift>+<space>",
    "<f8>",
    "<f9>",
    "<f10>",
    "<f11>",
)

_MACOS_NAMED_TRIGGERS = frozenset(
    {
        "space",
        "enter",
        "tab",
        "esc",
        "backspace",
        "delete",
        "home",
        "end",
        "page_up",
        "page_down",
        "up",
        "down",
        "left",
        "right",
    }
)


def is_macos_supported_trigger(trigger: str) -> bool:
    if len(trigger) == 1 and trigger.isascii() and trigger.isalnum():
        return True
    if trigger in _MACOS_NAMED_TRIGGERS:
        return True
    if trigger.startswith("f") and trigger[1:].isdigit():
        return 1 <= int(trigger[1:]) <= 20
    return False

HOTKEY_ACTIONS = (
    HotkeyAction(
        setting_key="toggle_recording",
        dispatch_action="toggle",
        label="Start / stop recording",
        default_combo="<ctrl>+<alt>+<space>",
        windows_suggestions=_TOGGLE_SUGGESTIONS,
        macos_suggestions=_TOGGLE_SUGGESTIONS,
    ),
    HotkeyAction(
        setting_key="force_english",
        dispatch_action="force_en",
        label="Quick language 1",
        default_combo="<ctrl>+<shift>+e",
        windows_suggestions=("<ctrl>+<shift>+e",),
        macos_suggestions=("<ctrl>+<shift>+e", "<shift>+<cmd>+e"),
        language_favorite_index=0,
    ),
    HotkeyAction(
        setting_key="force_spanish",
        dispatch_action="force_es",
        label="Quick language 2",
        default_combo="<ctrl>+<shift>+s",
        windows_suggestions=("<ctrl>+<shift>+s",),
        macos_suggestions=("<ctrl>+<shift>+s", "<shift>+<cmd>+s"),
        language_favorite_index=1,
    ),
    HotkeyAction(
        setting_key="force_language_3",
        dispatch_action="force_language_3",
        label="Quick language 3",
        default_combo="",
        windows_suggestions=("<ctrl>+<shift>+<f9>",),
        macos_suggestions=("<ctrl>+<shift>+<f9>", "<shift>+<cmd>+<f9>"),
        language_favorite_index=2,
    ),
)

HOTKEY_ACTION_BY_KEY = {action.setting_key: action for action in HOTKEY_ACTIONS}
DEFAULT_HOTKEYS = {
    action.setting_key: action.default_combo for action in HOTKEY_ACTIONS
}
