from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HotkeyAction:
    setting_key: str
    dispatch_action: str
    label: str
    default_combo: str
    windows_suggestions: tuple[str, ...]
    macos_suggestions: tuple[str, ...]

    def suggestions(self, platform: str) -> tuple[str, ...]:
        if platform == "darwin":
            return self.macos_suggestions
        return self.windows_suggestions


_TOGGLE_SUGGESTIONS = (
    "<ctrl>+<alt>+<space>",
    "<ctrl>+<shift>+<space>",
    "<f8>",
    "<f9>",
    "<f10>",
    "<f11>",
)

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
        label="Dictate in English",
        default_combo="<ctrl>+<shift>+e",
        windows_suggestions=("<ctrl>+<shift>+e",),
        macos_suggestions=("<ctrl>+<shift>+e", "<shift>+<cmd>+e"),
    ),
    HotkeyAction(
        setting_key="force_spanish",
        dispatch_action="force_es",
        label="Dictate in Spanish",
        default_combo="<ctrl>+<shift>+s",
        windows_suggestions=("<ctrl>+<shift>+s",),
        macos_suggestions=("<ctrl>+<shift>+s", "<shift>+<cmd>+s"),
    ),
)

HOTKEY_ACTION_BY_KEY = {action.setting_key: action for action in HOTKEY_ACTIONS}
DEFAULT_HOTKEYS = {
    action.setting_key: action.default_combo for action in HOTKEY_ACTIONS
}
