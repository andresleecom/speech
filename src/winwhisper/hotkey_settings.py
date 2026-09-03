from __future__ import annotations

import re
import sys
from collections.abc import Mapping

from .hotkey_actions import (
    HOTKEY_ACTION_BY_KEY,
    HOTKEY_ACTIONS,
    HotkeyAction,
    is_macos_supported_trigger,
)
from .hotkeys import combo_to_hotkey, parse_combo
from .mouse_buttons import (
    display_mouse_trigger,
    is_mouse_trigger,
    normalize_mouse_trigger,
    requires_modifier,
)

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
# Key names pynput reports on the Linux (X11) listener backend. Anything else
# would be saved happily and then never fire.
_LINUX_NAMED_TRIGGERS = frozenset(
    {
        "space",
        "enter",
        "tab",
        "esc",
        "backspace",
        "delete",
        "insert",
        "home",
        "end",
        "page_up",
        "page_down",
        "up",
        "down",
        "left",
        "right",
        "numpad_plus",
        "numpad_minus",
        "numpad_multiply",
        "numpad_divide",
        "numpad_decimal",
        *(f"numpad{digit}" for digit in range(10)),
    }
)
_DISABLED_VALUES = {"", "disabled", "none", "off"}
_LEGACY_MACOS_DEFAULTS = {
    "force_english": ("<ctrl>+<alt>+e", "<ctrl>+<shift>+e"),
    "force_spanish": ("<ctrl>+<alt>+s", "<ctrl>+<shift>+s"),
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
        mouse_trigger = normalize_mouse_trigger(token)
        if mouse_trigger is not None:
            trigger = mouse_trigger
            continue
        trigger = _TRIGGER_INPUT_ALIASES.get(token, token)

    if trigger is None:
        raise HotkeyConfigurationError("Choose a trigger key for the shortcut.")

    if is_mouse_trigger(trigger):
        return _normalize_mouse_combo(trigger, modifiers)

    if platform == "darwin" or _is_linux(platform):
        # The listener backends report these keys under pynput's names; the
        # Windows spelling would never match an event there.
        trigger = {"pageup": "page_up", "pagedown": "page_down"}.get(
            trigger, trigger
        )

    if platform == "darwin":
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
    language_favorites: object = None,
) -> dict[str, str]:
    """Validate a whole hotkey profile.

    Saved values are never replaced by defaults: an action missing from
    ``values`` stays missing, which is how an action is disabled. Only a brand
    new profile picks up ``default_hotkeys``, so changing a default cannot move
    a shortcut an existing user already relies on.
    """
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
                f"{action.label_for_favorites(language_favorites)} uses the same "
                f"shortcut as {previous_action.label_for_favorites(language_favorites)}."
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


def _normalize_mouse_combo(trigger: str, modifiers: set[str]) -> str:
    """Build a mouse combo.

    Mouse buttons skip the "needs a modifier or a function key" rule that keeps
    bare letters from hijacking typing, because a side button has no meaning to
    type over. Left click is the exception: bound bare, it would swallow the
    click needed to undo it.
    """
    if requires_modifier(trigger) and not modifiers:
        raise HotkeyConfigurationError(
            "Left click needs at least one modifier, otherwise it would stop "
            "you clicking anything. Use a side or middle button on its own."
        )

    ordered_modifiers = [name for name in _MODIFIER_ORDER if name in modifiers]
    return "+".join([*(f"<{name}>" for name in ordered_modifiers), f"<{trigger}>"])


def _plain_token(value: str) -> str:
    token = value.strip().lower()
    if token.startswith("<") and token.endswith(">"):
        token = token[1:-1]
    return re.sub(r"[\s_-]", "", token)


def _is_linux(platform: str) -> bool:
    return platform.startswith("linux")


def is_linux_supported_trigger(trigger: str) -> bool:
    """Whether the Linux listener backend can report this trigger key."""
    if len(trigger) == 1 and trigger.isascii():
        return True
    if trigger in _LINUX_NAMED_TRIGGERS:
        return True
    if trigger.startswith("f") and trigger[1:].isdigit():
        return 1 <= int(trigger[1:]) <= 20
    return False


def _validate_platform_trigger(combo: str, trigger: str, platform: str) -> None:
    if platform == "win32":
        combo_to_hotkey(combo)
        return
    if platform == "darwin":
        if not is_macos_supported_trigger(trigger):
            raise HotkeyConfigurationError(
                f"Unsupported macOS hotkey trigger key: {trigger!r}"
            )
        return
    if _is_linux(platform) and not is_linux_supported_trigger(trigger):
        raise HotkeyConfigurationError(
            f"Unsupported Linux hotkey trigger key: {trigger!r}. Use a letter, "
            "a number, a function key up to F20, or a named key such as Space, "
            "Enter, Page Up, or an arrow key."
        )


def _display_trigger(trigger: str) -> str:
    if is_mouse_trigger(trigger):
        return display_mouse_trigger(trigger)
    if trigger in _TRIGGER_LABELS:
        return _TRIGGER_LABELS[trigger]
    if trigger.startswith("f") and trigger[1:].isdigit():
        return trigger.upper()
    if len(trigger) == 1:
        return trigger.upper()
    return trigger.replace("_", " ").title()
