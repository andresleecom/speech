from __future__ import annotations

import re
import sys
from collections.abc import Mapping

from .hotkey_actions import HOTKEY_ACTION_BY_KEY, HOTKEY_ACTIONS, HotkeyAction
from .hotkeys import combo_to_hotkey, parse_combo

_MODIFIER_ORDER = ("ctrl", "alt", "shift", "cmd")
_MODIFIER_INPUT_ALIASES = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "option": "alt",
    "shift": "shift",
    "cmd": "cmd",
    "command": "cmd",
    "meta": "cmd",
    "super": "cmd",
    "win": "cmd",
    "windows": "cmd",
}
_TRIGGER_INPUT_ALIASES = {
    "spacebar": "space",
    "return": "enter",
    "escape": "esc",
    "del": "delete",
    "pgup": "pageup",
    "pageup": "pageup",
    "pgdown": "pagedown",
    "pagedown": "pagedown",
    "arrowup": "up",
    "arrowdown": "down",
    "arrowleft": "left",
    "arrowright": "right",
    "scrolllock": "scroll_lock",
    "printscreen": "print_screen",
    "capslock": "caps_lock",
    "numpadplus": "numpad_plus",
    "numplus": "numpad_plus",
    "kpplus": "numpad_plus",
    "add": "numpad_plus",
    "numpadminus": "numpad_minus",
    "numminus": "numpad_minus",
    "subtract": "numpad_minus",
    "numpadmultiply": "numpad_multiply",
    "nummultiply": "numpad_multiply",
    "multiply": "numpad_multiply",
    "numpaddivide": "numpad_divide",
    "numdivide": "numpad_divide",
    "divide": "numpad_divide",
    "numpaddecimal": "numpad_decimal",
}
_TRIGGER_LABELS = {
    "space": "Space",
    "enter": "Enter",
    "tab": "Tab",
    "esc": "Esc",
    "backspace": "Backspace",
    "delete": "Delete",
    "insert": "Insert",
    "home": "Home",
    "end": "End",
    "pageup": "Page Up",
    "pagedown": "Page Down",
    "page_up": "Page Up",
    "page_down": "Page Down",
    "up": "Arrow Up",
    "down": "Arrow Down",
    "left": "Arrow Left",
    "right": "Arrow Right",
    "numpad_plus": "Numpad +",
    "numpad_minus": "Numpad -",
}
_DISABLED_VALUES = {"", "disabled", "none", "off"}
_LEGACY_MACOS_DEFAULTS = {
    "force_english": ("<ctrl>+<alt>+e", "<ctrl>+<shift>+e"),
    "force_spanish": ("<ctrl>+<alt>+s", "<ctrl>+<shift>+s"),
}
_MAC_NAMED_TRIGGERS = {
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


class HotkeyConfigurationError(ValueError):
    pass


def normalize_hotkey_input(value: str, *, platform: str | None = None) -> str | None:
    platform = platform or sys.platform
    stripped = value.strip()
    if stripped.lower() in _DISABLED_VALUES:
        return None

    # Friendly labels contain the same symbols used as chord delimiters.
    # Protect them before splitting so an existing numpad binding round-trips.
    stripped = re.sub(
        r"numpad\s*\+$",
        "numpad_plus",
        stripped,
        flags=re.IGNORECASE,
    )
    stripped = re.sub(
        r"numpad\s*-$",
        "numpad_minus",
        stripped,
        flags=re.IGNORECASE,
    )
    tokens = [_plain_token(part) for part in stripped.split("+")]
    if any(not token for token in tokens):
        raise HotkeyConfigurationError(f"Invalid shortcut: {value!r}")

    modifiers: set[str] = set()
    trigger: str | None = None
    for token in tokens:
        modifier = _MODIFIER_INPUT_ALIASES.get(token)
        if modifier is not None:
            modifiers.add(modifier)
            continue
        if trigger is not None:
            raise HotkeyConfigurationError(
                "Use zero or more modifiers and exactly one trigger key."
            )
        trigger = _TRIGGER_INPUT_ALIASES.get(token, token)

    if trigger is None:
        raise HotkeyConfigurationError("Choose a trigger key for the shortcut.")

    if platform == "darwin":
        trigger = {"pageup": "page_up", "pagedown": "page_down"}.get(
            trigger, trigger
        )
        if "alt" in modifiers and len(trigger) == 1:
            raise HotkeyConfigurationError(
                "Option with a letter or number changes across keyboard layouts. "
                "Use Space, a function key, or a shortcut without Option."
            )

    is_function_key = trigger.startswith("f") and trigger[1:].isdigit()
    if not modifiers and not is_function_key:
        raise HotkeyConfigurationError(
            "Add at least one modifier, or choose a function key such as F8."
        )

    ordered_modifiers = [name for name in _MODIFIER_ORDER if name in modifiers]
    modifier_parts = [f"<{name}>" for name in ordered_modifiers]
    trigger_part = trigger if len(trigger) == 1 else f"<{trigger}>"
    combo = "+".join([*modifier_parts, trigger_part])

    try:
        parse_combo(combo)
        _validate_platform_trigger(combo, trigger, platform)
    except ValueError as exc:
        raise HotkeyConfigurationError(str(exc)) from exc
    return combo


def normalize_hotkey_profile(
    values: Mapping[str, str],
    *,
    platform: str | None = None,
) -> dict[str, str]:
    platform = platform or sys.platform
    unknown = set(values) - set(HOTKEY_ACTION_BY_KEY)
    if unknown:
        names = ", ".join(sorted(unknown))
        raise HotkeyConfigurationError(f"Unknown hotkey action: {names}")

    candidate_values = dict(values)
    if platform == "darwin":
        for action_key, (legacy, replacement) in _LEGACY_MACOS_DEFAULTS.items():
            current = candidate_values.get(action_key, "").strip().casefold()
            legacy_labels = {
                legacy.casefold(),
                display_hotkey(legacy, platform="darwin").casefold(),
            }
            if current in legacy_labels:
                candidate_values[action_key] = replacement

    normalized: dict[str, str] = {}
    owners_by_combo: dict[str, HotkeyAction] = {}
    for action in HOTKEY_ACTIONS:
        combo = normalize_hotkey_input(
            candidate_values.get(action.setting_key, ""),
            platform=platform,
        )
        if combo is None:
            continue
        previous_action = owners_by_combo.get(combo)
        if previous_action is not None:
            raise HotkeyConfigurationError(
                f"{action.label} uses the same shortcut as "
                f"{previous_action.label}."
            )
        owners_by_combo[combo] = action
        normalized[action.setting_key] = combo
    return normalized


def display_hotkey(combo: str | None, *, platform: str | None = None) -> str:
    if not combo:
        return "Disabled"
    platform = platform or sys.platform
    try:
        modifiers, trigger = parse_combo(combo)
    except ValueError:
        return combo

    modifier_labels = {
        "ctrl": "Control" if platform == "darwin" else "Ctrl",
        "alt": "Option" if platform == "darwin" else "Alt",
        "shift": "Shift",
        "cmd": "Command" if platform == "darwin" else "Win",
    }
    parts = [
        modifier_labels[name] for name in _MODIFIER_ORDER if name in modifiers
    ]
    parts.append(_display_trigger(trigger))
    return " + ".join(parts)


def _plain_token(value: str) -> str:
    token = value.strip().lower()
    if token.startswith("<") and token.endswith(">"):
        token = token[1:-1]
    return re.sub(r"[\s_-]", "", token)


def _validate_platform_trigger(combo: str, trigger: str, platform: str) -> None:
    if platform == "win32":
        combo_to_hotkey(combo)
        return
    if platform != "darwin":
        return
    if len(trigger) == 1 and trigger.isascii() and trigger.isalnum():
        return
    if trigger in _MAC_NAMED_TRIGGERS:
        return
    if trigger.startswith("f") and trigger[1:].isdigit():
        number = int(trigger[1:])
        if 1 <= number <= 20:
            return
    raise HotkeyConfigurationError(
        f"Unsupported macOS hotkey trigger key: {trigger!r}"
    )


def _display_trigger(trigger: str) -> str:
    if trigger in _TRIGGER_LABELS:
        return _TRIGGER_LABELS[trigger]
    if trigger.startswith("f") and trigger[1:].isdigit():
        return trigger.upper()
    if len(trigger) == 1:
        return trigger.upper()
    return trigger.replace("_", " ").title()
