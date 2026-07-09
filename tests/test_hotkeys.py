import os

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


def test_trigger_to_vk_numpad_and_oem_keys():
    assert trigger_to_vk("numpad_plus") == 0x6B
    assert trigger_to_vk("add") == 0x6B
    assert trigger_to_vk("numpad_minus") == 0x6D
    assert trigger_to_vk("numpad5") == 0x65
    assert trigger_to_vk("plus") == 0xBB


def test_combo_to_hotkey_ctrl_shift_numpad_plus():
    fs, vk = combo_to_hotkey("<ctrl>+<shift>+<numpad_plus>")
    assert fs == _MOD_CONTROL | _MOD_SHIFT
    assert vk == 0x6B


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


@pytest.mark.skipif(os.name != "nt", reason="Windows-only")
def test_native_overlay_does_not_mutate_shared_windll():
    """Regression: native_overlay set argtypes on the process-wide windll cache,
    clobbering the hotkey thread's GetMessageW binding (different MSG struct) and
    crashing its message loop after the first dictation."""
    import ctypes

    from winwhisper import native_overlay

    assert native_overlay.user32 is not ctypes.windll.user32
    assert native_overlay.gdi32 is not ctypes.windll.gdi32
    assert native_overlay.kernel32 is not ctypes.windll.kernel32
    assert (
        native_overlay.user32.GetMessageW is not ctypes.windll.user32.GetMessageW
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows-only")
def test_message_loop_survives_foreign_argtypes_clobber():
    """Regression: even if another module clobbers the shared windll bindings
    (the exact mechanism that killed hotkeys after the first take), the hotkey
    message loop must keep dispatching because it uses private handles."""
    import ctypes
    import time
    from ctypes import wintypes

    fired: list[str] = []
    manager = HotkeyManager({"toggle_recording": "<f13>"}, lambda a: fired.append(a))
    manager.start()
    assert manager._started.wait(2.0)
    thread_id = manager._thread_id
    assert thread_id is not None

    class ForeignMSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("message", wintypes.UINT),
            ("wParam", wintypes.WPARAM),
            ("lParam", wintypes.LPARAM),
            ("time", wintypes.DWORD),
            ("pt", wintypes.POINT),
        ]

    shared = ctypes.windll.user32
    old_argtypes = getattr(shared.GetMessageW, "argtypes", None)
    try:
        # Simulate native_overlay-style clobbering of the shared cache.
        shared.GetMessageW.argtypes = [
            ctypes.POINTER(ForeignMSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        ]
        post = ctypes.WinDLL("user32").PostThreadMessageW
        WM_HOTKEY = 0x0312
        for _ in range(2):
            assert post(thread_id, WM_HOTKEY, 1, 0)
            time.sleep(0.2)
        deadline = time.monotonic() + 2.0
        while len(fired) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        shared.GetMessageW.argtypes = old_argtypes

    assert fired == ["toggle", "toggle"]
    assert manager._thread is not None and manager._thread.is_alive()
    manager.stop()
