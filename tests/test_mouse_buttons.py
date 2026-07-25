import pytest

from winwhisper.hotkey_settings import (
    HotkeyConfigurationError,
    display_hotkey,
    normalize_hotkey_input,
)
from winwhisper.hotkeys import parse_combo
from winwhisper.mouse_buttons import (
    display_mouse_trigger,
    is_mouse_trigger,
    mouse_button_name,
    normalize_mouse_trigger,
    trigger_for_button_name,
)


def test_friendly_names_resolve_to_pynput_button_names():
    assert normalize_mouse_trigger("mouse back") == "mouse_x1"
    assert normalize_mouse_trigger("MouseX1") == "mouse_x1"
    assert normalize_mouse_trigger("mouse_forward") == "mouse_x2"
    assert normalize_mouse_trigger("mouse-middle") == "mouse_middle"
    assert normalize_mouse_trigger("mouse wheel") == "mouse_middle"


def test_unknown_buttons_pass_through_so_unusual_mice_still_bind():
    # X11 reports extra buttons as button8, button9, ... and Speech should not
    # need to know the model to bind them.
    assert normalize_mouse_trigger("mouse_button9") == "mouse_button9"
    assert display_mouse_trigger("mouse_button9") == "Mouse Button 9"


def test_non_mouse_tokens_are_rejected():
    assert normalize_mouse_trigger("space") is None
    assert normalize_mouse_trigger("mouse") is None
    assert normalize_mouse_trigger("f8") is None


def test_button_name_round_trips():
    assert mouse_button_name("mouse_x1") == "x1"
    assert trigger_for_button_name("x2") == "mouse_x2"
    assert trigger_for_button_name("middle") == "mouse_middle"
    assert is_mouse_trigger("mouse_x1") is True
    assert is_mouse_trigger("f8") is False


def test_side_buttons_bind_without_a_modifier():
    combo = normalize_hotkey_input("Mouse Back")

    assert combo == "<mouse_x1>"
    assert parse_combo(combo) == (frozenset(), "mouse_x1")
    assert display_hotkey(combo, platform="win32") == "Mouse Back"


def test_mouse_buttons_combine_with_modifiers_in_canonical_order():
    combo = normalize_hotkey_input("Shift + Ctrl + Mouse Forward")

    assert combo == "<ctrl>+<shift>+<mouse_x2>"
    assert display_hotkey(combo, platform="win32") == "Ctrl + Shift + Mouse Forward"


def test_left_click_needs_a_modifier_so_the_mouse_stays_usable():
    with pytest.raises(HotkeyConfigurationError, match="Left click needs"):
        normalize_hotkey_input("Left Click")

    assert normalize_hotkey_input("Ctrl + Left Click") == "<ctrl>+<mouse_left>"


def test_middle_and_right_are_bindable_on_their_own():
    assert normalize_hotkey_input("Middle Click") == "<mouse_middle>"
    assert normalize_hotkey_input("Right Click") == "<mouse_right>"


def test_saved_mouse_combo_round_trips_through_normalization():
    assert normalize_hotkey_input("<mouse_x1>") == "<mouse_x1>"
    assert normalize_hotkey_input("<ctrl>+<mouse_middle>") == "<ctrl>+<mouse_middle>"


def test_mouse_combos_are_accepted_on_macos_where_key_triggers_are_restricted():
    # is_macos_supported_trigger only knows about keys; mouse buttons must not
    # be caught by that allowlist.
    assert normalize_hotkey_input("Mouse Back", platform="darwin") == "<mouse_x1>"
