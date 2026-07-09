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


class _ImmediateThread:
    """Run the dispatch worker inline so its finally-reset happens synchronously."""

    def __init__(self, target=None, args=(), **kwargs):
        self._target = target
        self._args = args

    def start(self):
        if self._target is not None:
            self._target(*self._args)


def test_hotkey_toggle_survives_reset_while_modifiers_are_held(monkeypatch):
    """Regression for the v0.1.4 "second hotkey does nothing" bug.

    The dispatch worker resets chord state in its finally. Wiping the pressed
    modifiers there left the second Space tap failing the modifier match while
    Ctrl+Alt were still physically held, so the hotkey worked once then went
    dead until the modifiers were released and pressed again.
    """
    from winwhisper import hotkeys as hotkeys_mod

    actions = []
    manager = HotkeyManager(
        {"toggle_recording": "<ctrl>+<alt>+<space>"},
        lambda action: actions.append(action),
    )
    monkeypatch.setattr(manager, "_describe", _describe_test_key)
    # Simulate the OS query being unavailable so the match falls back to tracked
    # state - this isolates the reset fix (preserved modifiers) from the live
    # OS-key-state safety net.
    monkeypatch.setattr(manager, "_live_modifiers", lambda: None)
    # Run the dispatch worker (and its finally reset) inline, as the app does.
    monkeypatch.setattr(hotkeys_mod.threading, "Thread", _ImmediateThread)

    # Hold Ctrl+Alt, tap Space -> START (dispatch + finally reset run inline).
    manager._on_press("ctrl")
    manager._on_press("alt")
    manager._on_press("space")
    manager._on_release("space")  # only Space lifted; Ctrl+Alt stay down
    assert actions == ["toggle"]

    # Debounce legitimately blocks an instant re-fire; let time pass.
    manager._last_action_at["toggle"] = manager._last_action_at.get("toggle", 0) - 1.0

    # Still holding Ctrl+Alt; tap Space again -> STOP must fire.
    manager._on_press("space")
    assert actions == ["toggle", "toggle"]


def test_hotkey_live_modifiers_recover_lost_tracking(monkeypatch):
    """Even if tracked modifiers are lost entirely, an OS-confirmed chord fires."""
    actions = []
    manager = HotkeyManager(
        {"toggle_recording": "<ctrl>+<alt>+<space>"},
        lambda action: actions.append(action),
    )
    monkeypatch.setattr(manager, "_dispatch", lambda action: actions.append(action))
    monkeypatch.setattr(manager, "_describe", _describe_test_key)
    # OS reports Ctrl+Alt genuinely held, but tracking never saw the key-downs.
    monkeypatch.setattr(manager, "_live_modifiers", lambda: {"ctrl", "alt"})

    manager._on_press("space")

    assert actions == ["toggle"]


def test_hotkey_live_modifiers_override_stale_tracking(monkeypatch):
    """A stale tracked modifier must not fire the chord when the OS says it's up.

    Guards against a phantom toggle: if a modifier key-up was missed,
    _pressed_modifiers keeps a stale 'ctrl'/'alt', but the OS key state (empty,
    and authoritative on Windows) reports nothing held, so a bare Space is inert.
    """
    actions = []
    manager = HotkeyManager(
        {"toggle_recording": "<ctrl>+<alt>+<space>"},
        lambda action: actions.append(action),
    )
    monkeypatch.setattr(manager, "_dispatch", lambda action: actions.append(action))
    monkeypatch.setattr(manager, "_describe", _describe_test_key)
    # OS reports nothing physically held (empty set is authoritative, not None).
    monkeypatch.setattr(manager, "_live_modifiers", lambda: set())

    # Poison tracked state as if the Ctrl+Alt key-ups were missed.
    manager._pressed_modifiers.update({"ctrl", "alt"})

    manager._on_press("space")

    assert actions == []


def test_hotkey_rearms_listener_after_each_dispatch(monkeypatch):
    """The listener is re-armed after a press so a hook killed after its first
    callback (security software) still has a live hook for the next press."""
    from winwhisper import hotkeys as hotkeys_mod

    actions = []
    manager = HotkeyManager(
        {"toggle_recording": "<f8>"},
        lambda action: actions.append(action),
    )
    monkeypatch.setattr(manager, "_describe", lambda key: ("key", "f8"))
    monkeypatch.setattr(manager, "_live_modifiers", lambda: None)
    monkeypatch.setattr(hotkeys_mod.threading, "Thread", _ImmediateThread)
    installs = []
    monkeypatch.setattr(manager, "_install_listener", lambda: installs.append(1))
    manager._should_run = True  # simulate a running listener

    manager._on_press("f8")

    assert actions == ["toggle"]
    assert installs == [1]  # re-armed exactly once after the dispatch


def test_hotkey_rearm_is_noop_when_not_running(monkeypatch):
    manager = HotkeyManager({"toggle_recording": "<f8>"}, lambda action: None)
    installs = []
    monkeypatch.setattr(manager, "_install_listener", lambda: installs.append(1))

    manager.rearm()  # _should_run is False

    assert installs == []


def test_hotkey_callbacks_swallow_handler_exceptions(monkeypatch):
    """pynput stops the listener if a callback raises, so the wrappers must not
    let an exception escape - otherwise one bad event kills the hotkey."""
    manager = HotkeyManager({"toggle_recording": "<f8>"}, lambda action: None)

    def boom(key):
        raise RuntimeError("boom")

    monkeypatch.setattr(manager, "_on_press_impl", boom)
    monkeypatch.setattr(manager, "_on_release_impl", boom)

    manager._on_press("f8")  # must not raise
    manager._on_release("f8")  # must not raise


def _test_manager(actions, monkeypatch):
    manager = HotkeyManager(
        {"toggle_recording": "<ctrl>+<alt>+<space>"},
        lambda action: actions.append(action),
    )
    monkeypatch.setattr(manager, "_dispatch", lambda action: actions.append(action))
    monkeypatch.setattr(manager, "_describe", _describe_test_key)
    # Drive matches from the simulated tracked state, not the test machine's real
    # keys: None makes _on_press fall back to _pressed_modifiers.
    monkeypatch.setattr(manager, "_live_modifiers", lambda: None)
    return manager


def _describe_test_key(key):
    if key in {"ctrl", "alt"}:
        return "mod", key
    return "key", key
