"""Mouse-button vocabulary for hotkey combos.

Speech binds mouse buttons the same way it binds keys, so a combo can read
``<ctrl>+<mouse_back>`` or just ``<mouse_back>``. Names come from pynput's
``Button`` enum, which differs per platform: Windows and macOS report
``left``/``right``/``middle``/``x1``/``x2``, while X11 reports higher buttons as
``button8``, ``button9``, and so on. Rather than hard-code one mouse, any name
pynput reports is accepted and round-tripped, so a mouse with extra buttons
works as long as its buttons reach the OS as mouse events at all.
"""
from __future__ import annotations

import re
from typing import Final

MOUSE_PREFIX: Final = "mouse_"

# Friendly aliases for the buttons every platform names differently. The value
# is the canonical suffix, which is pynput's own Button name.
_BUTTON_ALIASES: Final = {
    "left": "left",
    "leftclick": "left",
    "right": "right",
    "rightclick": "right",
    "middle": "middle",
    "middleclick": "middle",
    "wheel": "middle",
    "wheelclick": "middle",
    "back": "x1",
    "x1": "x1",
    "button4": "x1",
    "thumb1": "x1",
    "forward": "x2",
    "x2": "x2",
    "button5": "x2",
    "thumb2": "x2",
}

_DISPLAY_LABELS: Final = {
    "left": "Left Click",
    "right": "Right Click",
    "middle": "Middle Click",
    "x1": "Mouse Back",
    "x2": "Mouse Forward",
}

# Binding a bare left click would leave no way to click Cancel in the very
# window used to undo it, so it always needs a modifier. Every other button is
# safe on its own.
MODIFIER_REQUIRED_BUTTONS: Final = frozenset({"left"})


def is_mouse_trigger(trigger: str) -> bool:
    return trigger.startswith(MOUSE_PREFIX)


def normalize_mouse_trigger(token: str) -> str | None:
    """Return the canonical ``mouse_*`` trigger for a token, else ``None``.

    Accepts what a user might type ("mouse back", "MouseX1") and what the
    capture UI records straight from pynput ("mouse_button9").
    """
    collapsed = re.sub(r"[\s_-]+", "", token.strip().lower())
    if collapsed.startswith("mouse"):
        suffix = collapsed[len("mouse") :]
    elif collapsed.endswith("click"):
        # "Middle Click" and friends, as shown in the settings window. Bare
        # "left"/"right" stay arrow keys, so the word "click" is what marks a
        # token as a mouse button.
        suffix = collapsed
    else:
        return None

    if suffix != "click" and suffix.endswith("click"):
        suffix = suffix[: -len("click")]
    if not suffix or suffix == "click":
        return None

    canonical = _BUTTON_ALIASES.get(suffix)
    if canonical is not None:
        return MOUSE_PREFIX + canonical
    # Unknown but well-formed names pass through so platform-specific buttons
    # such as X11's button9 stay bindable.
    if re.fullmatch(r"[a-z0-9]+", suffix):
        return MOUSE_PREFIX + suffix
    return None


def mouse_button_name(trigger: str) -> str:
    """Return the pynput ``Button`` name for a canonical mouse trigger."""
    if not is_mouse_trigger(trigger):
        raise ValueError(f"Not a mouse trigger: {trigger!r}")
    return trigger[len(MOUSE_PREFIX) :]


def trigger_for_button_name(name: str) -> str:
    """Return the canonical trigger for a pynput ``Button`` name."""
    normalized = normalize_mouse_trigger(MOUSE_PREFIX + str(name))
    if normalized is None:
        raise ValueError(f"Unsupported mouse button: {name!r}")
    return normalized


def requires_modifier(trigger: str) -> bool:
    return mouse_button_name(trigger) in MODIFIER_REQUIRED_BUTTONS


def display_mouse_trigger(trigger: str) -> str:
    name = mouse_button_name(trigger)
    if name in _DISPLAY_LABELS:
        return _DISPLAY_LABELS[name]
    match = re.fullmatch(r"button(\d+)", name)
    if match:
        return f"Mouse Button {match.group(1)}"
    return "Mouse " + name.replace("_", " ").title()
