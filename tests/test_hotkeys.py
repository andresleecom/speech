import pytest

from winwhisper.hotkeys import (
    HotkeyManager,
    _MOD_ALT,
    _MOD_CONTROL,
    _MOD_SHIFT,
    combo_to_hotkey,
    normalize_combo,
    parse_combo,
    trigger_to_vk,
)


def test_bare_named_key_gets_bracketed():
    assert normalize_combo("<ctrl>+<alt>+space") == "<ctrl>+<alt>+<space>"


def test_canonical_combo_unchanged():
    assert normalize_combo("<ctrl>+<alt>+<space>") == "<ctrl>+<alt>+<space>"


def test_single_character_key_unchanged():
    assert normalize_combo("<ctrl>+<alt>+e") == "<ctrl>+<alt>+e"


def test_parse_combo_named_trigger():
    assert parse_combo("<ctrl>+<alt>+<space>") == (frozenset({"ctrl", "alt"}), "space")


def test_parse_combo_bare_named_trigger():
    assert parse_combo("<ctrl>+<alt>+space") == (frozenset({"ctrl", "alt"}), "space")


def test_parse_combo_character_trigger():
    assert parse_combo("<ctrl>+<alt>+e") == (frozenset({"ctrl", "alt"}), "e")


def test_parse_combo_rejects_modifier_only():
    with pytest.raises(ValueError):
        parse_combo("<ctrl>+<alt>")


def test_parse_combo_rejects_two_triggers():
    with pytest.raises(ValueError):
        parse_combo("<ctrl>+a+b")


def test_trigger_to_vk_letters_digits_space():
    assert trigger_to_vk("e") == 0x45
    assert trigger_to_vk("s") == 0x53
    assert trigger_to_vk("5") == 0x35
    assert trigger_to_vk("space") == 0x20


def test_trigger_to_vk_function_keys():
    assert trigger_to_vk("f1") == 0x70
    assert trigger_to_vk("f8") == 0x77
    assert trigger_to_vk("f12") == 0x7B


def test_trigger_to_vk_rejects_unknown():
    with pytest.raises(ValueError):
        trigger_to_vk("nonsense_key")


def test_combo_to_hotkey_ctrl_alt_space():
    fs, vk = combo_to_hotkey("<ctrl>+<alt>+<space>")
    assert fs == _MOD_CONTROL | _MOD_ALT
    assert vk == 0x20


def test_combo_to_hotkey_ctrl_shift_space():
    fs, vk = combo_to_hotkey("<ctrl>+<shift>+space")
    assert fs == _MOD_CONTROL | _MOD_SHIFT
    assert vk == 0x20


def test_combo_to_hotkey_single_key_no_modifiers():
    fs, vk = combo_to_hotkey("<f8>")
    assert fs == 0
    assert vk == 0x77


def test_hotkey_manager_builds_bindings_and_skips_invalid():
    manager = HotkeyManager(
        {
            "toggle_recording": "<ctrl>+<alt>+<space>",
            "force_english": "<ctrl>+<alt>+e",
            "force_spanish": "not+a+valid+combo",  # two triggers -> skipped
        },
        lambda action: None,
    )
    actions = {action for _id, _fs, _vk, action, _combo in manager._bindings}
    assert actions == {"toggle", "force_en"}
    # Unique, stable ids per registered binding.
    ids = [hid for hid, _fs, _vk, _action, _combo in manager._bindings]
    assert len(ids) == len(set(ids))


def test_hotkey_manager_start_is_noop_off_windows(monkeypatch):
    import winwhisper.hotkeys as hotkeys_mod

    monkeypatch.setattr(hotkeys_mod.os, "name", "posix")
    manager = HotkeyManager({"toggle_recording": "<f8>"}, lambda action: None)
    manager.start()  # must not raise or start a thread
    assert manager._thread is None
