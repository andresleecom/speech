import pytest

from winwhisper.hotkey_settings import (
    HotkeyConfigurationError,
    display_hotkey,
    normalize_hotkey_input,
    normalize_hotkey_profile,
)


@pytest.mark.parametrize(
    ("value", "platform", "expected"),
    [
        ("Ctrl + Alt + Space", "win32", "<ctrl>+<alt>+<space>"),
        ("Control + Option + Space", "darwin", "<ctrl>+<alt>+<space>"),
        ("Windows + Shift + F8", "win32", "<shift>+<cmd>+<f8>"),
        ("Command + Shift + F8", "darwin", "<shift>+<cmd>+<f8>"),
        ("<ctrl>+<shift>+r", "win32", "<ctrl>+<shift>+r"),
        (
            "Ctrl + Shift + Numpad +",
            "win32",
            "<ctrl>+<shift>+<numpad_plus>",
        ),
        (
            "Ctrl + Shift + Numpad -",
            "win32",
            "<ctrl>+<shift>+<numpad_minus>",
        ),
    ],
)
def test_hotkey_input_accepts_windows_macos_and_config_labels(
    value, platform, expected
):
    assert normalize_hotkey_input(value, platform=platform) == expected


def test_hotkey_labels_use_platform_vocabulary():
    combo = "<ctrl>+<alt>+<shift>+<cmd>+<space>"

    assert display_hotkey(combo, platform="win32") == "Ctrl + Alt + Shift + Win + Space"
    assert (
        display_hotkey(combo, platform="darwin")
        == "Control + Option + Shift + Command + Space"
    )


def test_disabled_hotkey_is_removed_from_profile():
    profile = normalize_hotkey_profile(
        {
            "toggle_recording": "Ctrl + Alt + Space",
            "force_english": "Disabled",
            "force_spanish": "",
        },
        platform="win32",
    )

    assert profile == {"toggle_recording": "<ctrl>+<alt>+<space>"}


def test_duplicate_hotkeys_are_rejected_before_registration():
    with pytest.raises(HotkeyConfigurationError, match="same shortcut"):
        normalize_hotkey_profile(
            {
                "toggle_recording": "Ctrl + Alt + Space",
                "force_english": "Alt + Ctrl + Space",
            },
            platform="win32",
        )


def test_unknown_hotkey_action_is_rejected():
    with pytest.raises(HotkeyConfigurationError, match="Unknown hotkey action"):
        normalize_hotkey_profile(
            {"launch_missiles": "Ctrl + Alt + Space"},
            platform="win32",
        )


def test_bare_printable_key_is_rejected_but_function_key_is_allowed():
    with pytest.raises(HotkeyConfigurationError, match="modifier"):
        normalize_hotkey_input("R", platform="win32")

    assert normalize_hotkey_input("F8", platform="win32") == "<f8>"


def test_macos_rejects_option_letter_shortcuts_that_change_with_layout():
    with pytest.raises(HotkeyConfigurationError, match="keyboard layout"):
        normalize_hotkey_input("Control + Option + E", platform="darwin")

    assert (
        normalize_hotkey_input("Control + Option + Space", platform="darwin")
        == "<ctrl>+<alt>+<space>"
    )


def test_macos_rejects_function_keys_beyond_pynput_support():
    with pytest.raises(HotkeyConfigurationError, match="Unsupported macOS"):
        normalize_hotkey_input("F21", platform="darwin")


def test_macos_migrates_legacy_default_language_shortcuts_on_save():
    profile = normalize_hotkey_profile(
        {
            "toggle_recording": "Command + Shift + F8",
            "force_english": "Control + Option + E",
            "force_spanish": "<ctrl>+<alt>+s",
        },
        platform="darwin",
    )

    assert profile == {
        "toggle_recording": "<shift>+<cmd>+<f8>",
        "force_english": "<ctrl>+<shift>+e",
        "force_spanish": "<ctrl>+<shift>+s",
    }


def test_hotkey_labels_follow_configured_favorite_languages():
    from winwhisper.hotkey_actions import HOTKEY_ACTION_BY_KEY

    action = HOTKEY_ACTION_BY_KEY["force_english"]
    third_action = HOTKEY_ACTION_BY_KEY["force_language_3"]

    assert action.label_for_favorites(["fr", "ja", None]) == "Dictate in French"
    assert third_action.label_for_favorites(["fr", "ja", None]) == (
        "Quick language 3 (not set)"
    )


def test_duplicate_hotkeys_name_the_configured_favorite_language():
    with pytest.raises(HotkeyConfigurationError, match="Dictate in French"):
        normalize_hotkey_profile(
            {
                "toggle_recording": "Ctrl + Alt + Space",
                "force_english": "Ctrl + Alt + Space",
            },
            platform="win32",
            language_favorites=["fr", "es", None],
        )


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("<ctrl>+<shift>+<scroll_lock>", "<ctrl>+<shift>+<scroll_lock>"),
        ("<ctrl>+<shift>+<print_screen>", "<ctrl>+<shift>+<print_screen>"),
        (
            "<ctrl>+<shift>+<num_multiply>",
            "<ctrl>+<shift>+<numpad_multiply>",
        ),
    ],
)
def test_windows_named_trigger_labels_round_trip(stored, expected):
    label = display_hotkey(stored, platform="win32")

    assert normalize_hotkey_input(label, platform="win32") == expected


def test_toggle_suggestions_drop_keys_apps_already_own():
    from winwhisper.hotkey_actions import HOTKEY_ACTION_BY_KEY

    toggle = HOTKEY_ACTION_BY_KEY["toggle_recording"]

    for platform in ("win32", "darwin", "linux"):
        suggestions = toggle.suggestions(platform)
        # F10 opens menus and F11 toggles full screen almost everywhere.
        assert "<f10>" not in suggestions
        assert "<f11>" not in suggestions
        assert "<f8>" in suggestions


def test_linux_accepts_page_up_and_rejects_keys_pynput_cannot_report():
    assert (
        normalize_hotkey_input("Ctrl + Alt + Page Up", platform="linux")
        == "<ctrl>+<alt>+<page_up>"
    )
    assert (
        normalize_hotkey_input("<ctrl>+<alt>+<pageup>", platform="linux")
        == "<ctrl>+<alt>+<page_up>"
    )

    for misspelling in ("Ctrl + Alt + Page Upp", "Ctrl + Alt + PgUpp"):
        with pytest.raises(HotkeyConfigurationError, match="Unsupported Linux"):
            normalize_hotkey_input(misspelling, platform="linux")

    with pytest.raises(HotkeyConfigurationError, match="Unsupported Linux"):
        normalize_hotkey_input("Ctrl + Alt + F21", platform="linux")


def test_linux_keeps_the_keys_the_listener_backend_reports():
    assert normalize_hotkey_input("Ctrl + Alt + Space", platform="linux") == (
        "<ctrl>+<alt>+<space>"
    )
    assert normalize_hotkey_input("F8", platform="linux") == "<f8>"
    assert normalize_hotkey_input("Ctrl + Shift + R", platform="linux") == (
        "<ctrl>+<shift>+r"
    )
    assert normalize_hotkey_input("Ctrl + Shift + Numpad +", platform="linux") == (
        "<ctrl>+<shift>+<numpad_plus>"
    )


def test_saved_profile_with_the_old_defaults_is_left_alone():
    saved = {
        "toggle_recording": "<ctrl>+<alt>+<space>",
        "force_english": "<ctrl>+<shift>+e",
        "force_spanish": "<ctrl>+<shift>+s",
    }

    assert normalize_hotkey_profile(dict(saved), platform="win32") == saved


def test_normalize_profile_never_substitutes_a_default_for_a_saved_value():
    profile = normalize_hotkey_profile(
        {"toggle_recording": "Ctrl + Shift + F9"},
        platform="win32",
    )

    # The absent actions stay absent, and the saved toggle keeps its combo.
    assert profile == {"toggle_recording": "<ctrl>+<shift>+<f9>"}
