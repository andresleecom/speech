import pytest

from winwhisper.hotkeys import HotkeyManager, normalize_combo, parse_combo


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


def test_hotkey_suppresses_trigger_repeat_while_chord_is_held(monkeypatch):
    actions = []
    manager = _test_manager(actions, monkeypatch)

    manager._on_press("ctrl")
    manager._on_press("alt")
    manager._on_press("space")
    manager._on_press("space")

    assert actions == ["toggle"]


def test_hotkey_recovers_when_trigger_release_is_missed(monkeypatch):
    actions = []
    manager = _test_manager(actions, monkeypatch)

    manager._on_press("ctrl")
    manager._on_press("alt")
    manager._on_press("space")

    # Windows global hooks can occasionally miss the trigger key release.
    # Releasing either modifier still marks the previous chord as finished.
    manager._on_release("ctrl")
    manager._on_release("alt")

    manager._on_press("ctrl")
    manager._on_press("alt")
    manager._on_press("space")

    assert actions == ["toggle", "toggle"]


def test_hotkey_ignores_events_while_listener_suppressed(monkeypatch):
    from winwhisper import hotkeys as hotkeys_mod

    actions = []
    manager = _test_manager(actions, monkeypatch)

    hotkeys_mod.set_listener_suppressed(True)
    try:
        manager._on_press("ctrl")
        manager._on_press("alt")
        manager._on_press("space")
    finally:
        hotkeys_mod.set_listener_suppressed(False)

    assert actions == []

    manager.reset_state()
    manager._on_press("ctrl")
    manager._on_press("alt")
    manager._on_press("space")

    assert actions == ["toggle"]


def test_hotkey_reset_state_allows_second_chord_without_release(monkeypatch):
    actions = []
    manager = _test_manager(actions, monkeypatch)

    manager._on_press("ctrl")
    manager._on_press("alt")
    manager._on_press("space")
    # Missed releases + synthetic paste pollution, then explicit reset.
    manager.reset_state()
    # Debounce is intentional; simulate time passing after the first fire.
    manager._last_action_at["toggle"] = manager._last_action_at.get("toggle", 0) - 1.0
    manager._on_press("ctrl")
    manager._on_press("alt")
    manager._on_press("space")

    assert actions == ["toggle", "toggle"]


def test_hotkey_recovers_when_space_release_is_missed_without_modifier_edge(monkeypatch):
    """After first chord, Windows sometimes never delivers Space key-up.

    A second full chord must still fire even if Space stayed "down" in state
    and the user re-presses Space without a fresh modifier edge clearing it.
    """
    actions = []
    manager = _test_manager(actions, monkeypatch)

    manager._on_press("ctrl")
    manager._on_press("alt")
    manager._on_press("space")
    assert actions == ["toggle"]

    # No space release. Time passes past the hold window (missed key-up).
    manager._trigger_down_at["space"] = manager._trigger_down_at["space"] - 1.0
    manager._last_action_at["toggle"] = manager._last_action_at.get("toggle", 0) - 1.0

    # Same modifiers still "down"; second Space press must re-arm.
    manager._on_press("space")

    assert actions == ["toggle", "toggle"]


def _test_manager(actions, monkeypatch):
    manager = HotkeyManager(
        {"toggle_recording": "<ctrl>+<alt>+<space>"},
        lambda action: actions.append(action),
    )
    monkeypatch.setattr(manager, "_dispatch", lambda action: actions.append(action))
    monkeypatch.setattr(manager, "_describe", _describe_test_key)
    return manager


def _describe_test_key(key):
    if key in {"ctrl", "alt"}:
        return "mod", key
    return "key", key
