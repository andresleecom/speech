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
from .hotkeys import (
    altgr_produces_character,
    character_for_virtual_key,
    combo_to_hotkey,
    parse_combo,
    trigger_to_vk,
)
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
# Tk keysyms that are modifiers alone; a KeyPress of these is not a chord yet.
_MODIFIER_KEYSYMS = frozenset(
    {
        "shift_l",
        "shift_r",
        "control_l",
        "control_r",
        "alt_l",
        "alt_r",
        "meta_l",
        "meta_r",
        "super_l",
        "super_r",
        "caps_lock",
        "num_lock",
        "scroll_lock",
        "alt_graph",
        "iso_level3_shift",
        "mode_switch",
    }
)
# Tk / X11 keysym → stored trigger name (or a single character for OEM keys).
_KEYSYM_TO_TRIGGER = {
    "space": "space",
    "return": "enter",
    "kp_enter": "enter",
    "tab": "tab",
    "escape": "esc",
    "backspace": "backspace",
    "delete": "delete",
    "insert": "insert",
    "home": "home",
    "end": "end",
    "prior": "page_up",
    "next": "page_down",
    "page_up": "page_up",
    "page_down": "page_down",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "kp_add": "numpad_plus",
    "kp_subtract": "numpad_minus",
    "kp_multiply": "numpad_multiply",
    "kp_divide": "numpad_divide",
    "kp_decimal": "numpad_decimal",
    "kp_0": "numpad0",
    "kp_1": "numpad1",
    "kp_2": "numpad2",
    "kp_3": "numpad3",
    "kp_4": "numpad4",
    "kp_5": "numpad5",
    "kp_6": "numpad6",
    "kp_7": "numpad7",
    "kp_8": "numpad8",
    "kp_9": "numpad9",
    "less": "<",
    "greater": ">",
    "comma": ",",
    "period": ".",
    "slash": "/",
    "backslash": "\\",
    "semicolon": ";",
    "apostrophe": "'",
    "quoteleft": "`",
    "bracketleft": "[",
    "bracketright": "]",
    "minus": "-",
    "equal": "=",
    "ntilde": "ñ",
    "Ntilde": "ñ",
    "masculine": "º",
    "ordfeminine": "ª",
    "plusminus": "±",
}
# Windows virtual-key → canonical trigger when the keycode is unambiguous.
_VK_TO_TRIGGER = {
    0x20: "space",
    0x0D: "enter",
    0x09: "tab",
    0x1B: "esc",
    0x08: "backspace",
    0x2E: "delete",
    0x2D: "insert",
    0x24: "home",
    0x23: "end",
    0x21: "page_up",
    0x22: "page_down",
    0x26: "up",
    0x28: "down",
    0x25: "left",
    0x27: "right",
    0x13: "pause",
    0x91: "scroll_lock",
    0x2C: "print_screen",
    0x6B: "numpad_plus",
    0x6D: "numpad_minus",
    0x6A: "numpad_multiply",
    0x6F: "numpad_divide",
    0x6E: "numpad_decimal",
    0x60: "numpad0",
    0x61: "numpad1",
    0x62: "numpad2",
    0x63: "numpad3",
    0x64: "numpad4",
    0x65: "numpad5",
    0x66: "numpad6",
    0x67: "numpad7",
    0x68: "numpad8",
    0x69: "numpad9",
}
# Tk event.state bits used while recording a chord.
_TK_SHIFT = 0x0001
_TK_CONTROL = 0x0004
_TK_ALT_WIN = 0x20000
_TK_ALT_LINUX = 0x0008  # Mod1; on Windows this bit is NumLock instead
_TK_SUPER_LINUX = 0x0040  # Mod4


class HotkeyConfigurationError(ValueError):
    pass


def combo_from_key_event(
    *,
    keycode: int,
    keysym: str,
    state: int,
    platform: str,
    extra_modifiers: tuple[str, ...] | list[str] = (),
) -> str | None:
    """Turn a Tk ``KeyPress`` into a serialized hotkey combo.

    Returns ``None`` for a bare modifier press, or for a printable key pressed
    without modifiers (same rule as ``normalize_hotkey_input``). Function keys
    may stand alone.
    """
    keysym_name = (keysym or "").strip()
    if keysym_name.lower() in _MODIFIER_KEYSYMS:
        return None

    modifiers: set[str] = {name for name in extra_modifiers if name in _MODIFIER_ORDER}
    if state & _TK_SHIFT:
        modifiers.add("shift")
    if state & _TK_CONTROL:
        modifiers.add("ctrl")
    if platform == "win32":
        if state & _TK_ALT_WIN:
            modifiers.add("alt")
    else:
        if state & _TK_ALT_LINUX:
            modifiers.add("alt")
        if state & _TK_SUPER_LINUX:
            modifiers.add("cmd")

    trigger = _trigger_from_key_event(keycode, keysym_name, platform)
    if trigger is None:
        return None

    is_function_key = trigger.startswith("f") and trigger[1:].isdigit()
    if not modifiers and not is_function_key:
        return None

    ordered_modifiers = [name for name in _MODIFIER_ORDER if name in modifiers]
    trigger_part = trigger if len(trigger) == 1 else f"<{trigger}>"
    return "+".join([*(f"<{name}>" for name in ordered_modifiers), trigger_part])


def _trigger_from_key_event(keycode: int, keysym: str, platform: str) -> str | None:
    """Resolve the trigger token for a KeyPress on the given platform."""
    if platform == "win32":
        named = _VK_TO_TRIGGER.get(keycode)
        if named is not None:
            return named
        if 0x70 <= keycode <= 0x87:
            return f"f{keycode - 0x70 + 1}"
        if 0x41 <= keycode <= 0x5A:
            return chr(keycode + 32)
        if 0x30 <= keycode <= 0x39:
            return chr(keycode)
        # OEM / layout-specific keys: prefer the physical key's character from
        # any installed layout over Tk's keysym (which follows the active
        # input language and can report e.g. "backslash" for the ISO <> key).
        try:
            layout_char = character_for_virtual_key(keycode)
        except OSError:
            layout_char = None
        if layout_char is not None:
            return layout_char

    keysym_trigger = _KEYSYM_TO_TRIGGER.get(keysym) or _KEYSYM_TO_TRIGGER.get(
        keysym.lower()
    )
    if keysym_trigger is not None:
        if platform == "win32" or _is_linux(platform):
            # pageup spelling is Windows-only in the name table; listeners use
            # the underscored form on Linux/macOS.
            return {"pageup": "page_up", "pagedown": "page_down"}.get(
                keysym_trigger, keysym_trigger
            )
        return keysym_trigger

    if len(keysym) == 1:
        return keysym.lower() if keysym.isascii() and keysym.isalpha() else keysym

    lowered = keysym.lower()
    if lowered.startswith("f") and lowered[1:].isdigit():
        return lowered
    if lowered in _TRIGGER_INPUT_ALIASES:
        alias = _TRIGGER_INPUT_ALIASES[lowered]
        if _is_linux(platform) or platform == "darwin":
            return {"pageup": "page_up", "pagedown": "page_down"}.get(alias, alias)
        return alias
    return None


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

    if (
        platform == "win32"
        and "ctrl" in modifiers
        and "alt" in modifiers
        and len(trigger) == 1
    ):
        _reject_altgr_typing_chord(trigger)

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


def _reject_altgr_typing_chord(trigger: str) -> None:
    """Reject Ctrl+Alt+key when AltGr already types a character with that key."""
    try:
        vk = trigger_to_vk(trigger)
    except ValueError:
        return
    produced = altgr_produces_character(vk)
    if produced is None:
        return
    if trigger.isascii() and trigger.isalpha():
        key_label = trigger.upper()
    else:
        key_label = trigger
    raise HotkeyConfigurationError(
        f'Ctrl + Alt + {key_label} types "{produced}" on your keyboard layout; '
        "choose another combination."
    )


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
