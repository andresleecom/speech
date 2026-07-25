import os
import sys
import types

import pytest

from winwhisper.hotkeys import HotkeyManager, _MouseHotkeyBackend

WM_LBUTTONDOWN = 0x0201
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208

_WINDOWS_ONLY = pytest.mark.skipif(
    os.name != "nt", reason="pynput's win32 hook internals only import on Windows"
)


class _FakeSuppress(Exception):
    """Stand-in for pynput's SuppressException."""


class _FakeListener:
    """Models pynput: suppression is requested by *raising*, not returning.

    The first version of this fake merely counted calls, which let a filter that
    swallowed the exception look correct in tests while suppressing nothing and
    never dispatching in production.
    """

    def __init__(self):
        self.suppressed = 0

    def suppress_event(self):
        self.suppressed += 1
        raise _FakeSuppress()


def _run_filter(backend, msg, data):
    """Call the filter; return True if suppression was requested."""
    try:
        backend._win32_event_filter(msg, data)
    except _FakeSuppress:
        return True
    return False


class _FakeLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def exception(self, *a, **k):
        raise AssertionError("handler raised; pynput would tear the hook down")


def _backend(bindings, modifiers=frozenset()):
    dispatched = []
    backend = _MouseHotkeyBackend(
        bindings,
        dispatched.append,
        _FakeLogger(),
        lambda: set(modifiers),
    )
    backend._listener = _FakeListener()
    return backend, dispatched


def _x_event(index):
    return types.SimpleNamespace(mouseData=index << 16)


def test_bound_side_button_dispatches_and_is_suppressed():
    backend, dispatched = _backend([(frozenset(), "x1", "toggle", "<mouse_x1>")])

    suppressed = _run_filter(backend, WM_XBUTTONDOWN, _x_event(1))

    # Both halves matter: the action must fire *and* the click must be swallowed.
    # Dispatching after suppress_event silently loses the action, because that
    # call raises.
    assert dispatched == ["toggle"]
    assert suppressed is True


def test_the_suppression_signal_is_not_swallowed_by_error_handling():
    # Regression: a blanket except around the whole filter caught pynput's
    # SuppressException, so nothing was ever suppressed and the action was
    # never dispatched, while an error was logged on every single press.
    backend, _ = _backend([(frozenset(), "x1", "toggle", "<mouse_x1>")])

    with pytest.raises(_FakeSuppress):
        backend._win32_event_filter(WM_XBUTTONDOWN, _x_event(1))


def test_matching_release_is_suppressed_so_no_dangling_button_up_escapes():
    backend, _ = _backend([(frozenset(), "x1", "toggle", "<mouse_x1>")])

    pressed = _run_filter(backend, WM_XBUTTONDOWN, _x_event(1))
    released = _run_filter(backend, WM_XBUTTONUP, _x_event(1))

    assert pressed is True
    assert released is True


def test_unbound_buttons_are_never_suppressed():
    backend, dispatched = _backend([(frozenset(), "x1", "toggle", "<mouse_x1>")])

    assert _run_filter(backend, WM_XBUTTONDOWN, _x_event(2)) is False  # unbound
    assert (
        _run_filter(backend, WM_LBUTTONDOWN, types.SimpleNamespace(mouseData=0))
        is False
    )
    assert _run_filter(backend, WM_XBUTTONUP, _x_event(2)) is False
    assert dispatched == []


def test_modifier_combo_only_fires_while_the_modifier_is_held():
    binding = [(frozenset({"ctrl"}), "middle", "toggle", "<ctrl>+<mouse_middle>")]
    plain = types.SimpleNamespace(mouseData=0)

    without, dispatched_without = _backend(binding, modifiers=frozenset())
    assert _run_filter(without, WM_MBUTTONDOWN, plain) is False
    assert dispatched_without == []

    with_ctrl, dispatched_with = _backend(binding, modifiers=frozenset({"ctrl"}))
    assert _run_filter(with_ctrl, WM_MBUTTONDOWN, plain) is True
    assert dispatched_with == ["toggle"]


def test_synthetic_paste_suppression_window_is_respected(monkeypatch):
    import winwhisper.hotkeys as hotkeys_module

    backend, dispatched = _backend([(frozenset(), "x1", "toggle", "<mouse_x1>")])
    monkeypatch.setattr(hotkeys_module, "listener_is_suppressed", lambda: True)

    assert _run_filter(backend, WM_XBUTTONDOWN, _x_event(1)) is False
    assert dispatched == []


@_WINDOWS_ONLY
def test_real_pynput_suppression_exception_reaches_its_own_handler():
    """Bind to the actual dependency, not just our stand-in for it."""
    from pynput._util.win32 import SystemHook

    class _RealListener:
        def suppress_event(self):
            raise SystemHook.SuppressException()

    dispatched = []
    backend = _MouseHotkeyBackend(
        [(frozenset(), "x1", "toggle", "<mouse_x1>")],
        dispatched.append,
        _FakeLogger(),
        lambda: set(),
    )
    backend._listener = _RealListener()

    with pytest.raises(SystemHook.SuppressException):
        backend._win32_event_filter(WM_XBUTTONDOWN, _x_event(1))
    assert dispatched == ["toggle"]


def test_a_failing_modifier_read_never_raises_into_the_hook():
    # Raising here would make pynput tear down the hook and wedge the mouse.
    logged = []

    class _Logger(_FakeLogger):
        def exception(self, *a, **k):
            logged.append(a)

    def explode():
        raise OSError("no user32 today")

    backend = _MouseHotkeyBackend(
        [(frozenset(), "x1", "toggle", "<mouse_x1>")],
        lambda action: None,
        _Logger(),
        explode,
    )
    backend._listener = _FakeListener()

    # Must not raise: pynput tears the hook down on an unexpected exception,
    # which would leave the mouse wedged.
    assert _run_filter(backend, WM_XBUTTONDOWN, _x_event(1)) is False

    assert logged
    assert backend._listener.suppressed == 0


def test_manager_routes_mouse_combos_away_from_register_hotkey():
    manager = HotkeyManager(
        {"toggle_recording": "<mouse_x1>", "force_english": "<ctrl>+<shift>+e"},
        lambda action: None,
    )

    mouse_combos = [combo for *_b, combo in manager._mouse_bindings]
    assert mouse_combos == ["<mouse_x1>"]
    # RegisterHotKey cannot express a mouse button, so it must not appear there.
    assert all(combo != "<mouse_x1>" for *_b, combo in manager._bindings)
    assert manager._rejected_combos == []


def test_manager_keeps_mouse_button_names_in_pynput_form():
    manager = HotkeyManager({"toggle_recording": "<ctrl>+<mouse_x2>"}, lambda a: None)

    modifiers, button, action, combo = manager._mouse_bindings[0]
    assert modifiers == frozenset({"ctrl"})
    assert button == "x2"
    assert action == "toggle"
    assert combo == "<ctrl>+<mouse_x2>"


def _install_fake_pynput(monkeypatch, clicks):
    """Fake pynput.mouse whose listener replays the given clicks on start."""
    started = {}

    class FakeListener:
        def __init__(self, on_click=None, **kwargs):
            self.on_click = on_click
            self.stopped = False
            started["listener"] = self

        def start(self):
            for name, pressed in clicks:
                if self.stopped:
                    return
                self.on_click(0, 0, types.SimpleNamespace(name=name), pressed)

        def stop(self):
            self.stopped = True

    mouse_module = types.ModuleType("pynput.mouse")
    mouse_module.Listener = FakeListener
    package = types.ModuleType("pynput")
    package.mouse = mouse_module
    monkeypatch.setitem(sys.modules, "pynput", package)
    monkeypatch.setitem(sys.modules, "pynput.mouse", mouse_module)
    return started


def test_capture_records_the_pressed_side_button(monkeypatch):
    from winwhisper.mouse_capture import MouseCapture

    _install_fake_pynput(monkeypatch, [("x1", True)])
    monkeypatch.setattr("winwhisper.hotkeys.windows_modifier_state", lambda: set())
    monkeypatch.setattr("os.name", "nt")

    captured = []
    MouseCapture(captured.append, timeout=30).start()

    assert captured == ["<mouse_x1>"]


def test_capture_ignores_the_bare_left_click_that_started_it(monkeypatch):
    from winwhisper.mouse_capture import MouseCapture

    # The user clicks "Record" with the left button; that press must not be
    # recorded as the shortcut. The side button that follows is the real answer.
    _install_fake_pynput(monkeypatch, [("left", True), ("x2", True)])
    monkeypatch.setattr("winwhisper.hotkeys.windows_modifier_state", lambda: set())
    monkeypatch.setattr("os.name", "nt")

    captured = []
    MouseCapture(captured.append, timeout=30).start()

    assert captured == ["<mouse_x2>"]


def test_capture_includes_held_modifiers(monkeypatch):
    from winwhisper.mouse_capture import MouseCapture

    _install_fake_pynput(monkeypatch, [("middle", True)])
    monkeypatch.setattr(
        "winwhisper.hotkeys.windows_modifier_state", lambda: {"ctrl", "shift"}
    )
    monkeypatch.setattr("os.name", "nt")

    captured = []
    MouseCapture(captured.append, timeout=30).start()

    assert captured == ["<ctrl>+<shift>+<mouse_middle>"]


def test_capture_reports_only_the_first_button(monkeypatch):
    from winwhisper.mouse_capture import MouseCapture

    _install_fake_pynput(monkeypatch, [("x1", True), ("x2", True)])
    monkeypatch.setattr("winwhisper.hotkeys.windows_modifier_state", lambda: set())
    monkeypatch.setattr("os.name", "nt")

    captured = []
    MouseCapture(captured.append, timeout=30).start()

    assert captured == ["<mouse_x1>"]


def test_captured_combo_survives_normalization():
    from winwhisper.hotkey_settings import normalize_hotkey_input
    from winwhisper.mouse_capture import build_combo

    combo = build_combo({"shift", "ctrl"}, "mouse_x1")

    assert combo == "<ctrl>+<shift>+<mouse_x1>"
    assert normalize_hotkey_input(combo) == combo
