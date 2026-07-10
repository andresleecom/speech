import sys
import types

from winwhisper.inserter import insert_text, resolve_paste_shortcut


class FakeClipboard(types.ModuleType):
    def __init__(self) -> None:
        super().__init__("pyperclip")
        self.value = "previous clipboard"

    def paste(self) -> str:
        return self.value

    def copy(self, text: str) -> None:
        self.value = text


class FakePressed:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


class FakeKeyboard:
    def __init__(self, events: list[tuple[str, str]]) -> None:
        self._events = events

    def pressed(self, key: str) -> FakePressed:
        self._events.append(("pressed", key))
        return FakePressed()

    def press(self, key: str) -> None:
        self._events.append(("press", key))

    def release(self, key: str) -> None:
        self._events.append(("release", key))


def test_insert_text_leaves_dictation_on_clipboard(monkeypatch):
    clipboard = FakeClipboard()
    events: list[tuple[str, str]] = []
    sleeps: list[float] = []
    keyboard_module = types.ModuleType("pynput.keyboard")
    keyboard_module.Controller = lambda: FakeKeyboard(events)
    keyboard_module.Key = types.SimpleNamespace(ctrl="ctrl", shift="shift")
    pynput_module = types.ModuleType("pynput")
    pynput_module.keyboard = keyboard_module

    monkeypatch.setitem(sys.modules, "pyperclip", clipboard)
    monkeypatch.setitem(sys.modules, "pynput", pynput_module)
    monkeypatch.setitem(sys.modules, "pynput.keyboard", keyboard_module)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("winwhisper.inserter.time.sleep", sleeps.append)

    assert insert_text("dictated text") is True
    assert clipboard.value == "dictated text"
    assert events == [
        ("pressed", "ctrl"),
        ("press", "v"),
        ("release", "v"),
    ]
    assert sleeps == []


def test_insert_text_can_use_ctrl_shift_v(monkeypatch):
    clipboard = FakeClipboard()
    events: list[tuple[str, str]] = []
    keyboard_module = types.ModuleType("pynput.keyboard")
    keyboard_module.Controller = lambda: FakeKeyboard(events)
    keyboard_module.Key = types.SimpleNamespace(ctrl="ctrl", shift="shift")
    pynput_module = types.ModuleType("pynput")
    pynput_module.keyboard = keyboard_module

    monkeypatch.setitem(sys.modules, "pyperclip", clipboard)
    monkeypatch.setitem(sys.modules, "pynput", pynput_module)
    monkeypatch.setitem(sys.modules, "pynput.keyboard", keyboard_module)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("winwhisper.inserter.time.sleep", lambda _: None)

    assert insert_text("dictated text", shortcut="ctrl_shift_v") is True
    assert clipboard.value == "dictated text"
    assert events == [
        ("pressed", "ctrl"),
        ("pressed", "shift"),
        ("press", "v"),
        ("release", "v"),
    ]


def test_terminal_process_uses_ctrl_shift_v(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert resolve_paste_shortcut("clipboard_ctrl_v", "WindowsTerminal.exe") == "ctrl_shift_v"
    assert resolve_paste_shortcut("auto", "wezterm-gui.exe") == "ctrl_shift_v"


def test_non_terminal_process_uses_ctrl_v(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert resolve_paste_shortcut("auto", "notepad.exe") == "ctrl_v"


def test_macos_always_uses_cmd_v(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert resolve_paste_shortcut("auto", None) == "cmd_v"
    assert resolve_paste_shortcut("auto", "iTerm2") == "cmd_v"
    assert resolve_paste_shortcut("clipboard_ctrl_shift_v", None) == "cmd_v"


def test_insert_text_cmd_v_uses_quartz_on_macos(monkeypatch):
    clipboard = FakeClipboard()
    events: list[tuple[object, ...]] = []
    quartz = types.SimpleNamespace(
        CGEventCreateKeyboardEvent=lambda _source, keycode, pressed: events.append(
            ("create", keycode, pressed)
        )
        or {"pressed": pressed},
        CGEventSetFlags=lambda event, flags: events.append(
            ("flags", event["pressed"], flags)
        ),
        CGEventPost=lambda tap, event: events.append(("post", tap, event["pressed"])),
        kCGEventFlagMaskCommand="command",
        kCGHIDEventTap="hid",
    )

    monkeypatch.setitem(sys.modules, "pyperclip", clipboard)
    monkeypatch.setitem(sys.modules, "Quartz", quartz)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("winwhisper.inserter.time.sleep", lambda _: None)

    assert insert_text("dictated text", shortcut="cmd_v") is True
    assert events == [
        ("create", 0x09, True),
        ("flags", True, "command"),
        ("post", "hid", True),
        ("create", 0x09, False),
        ("flags", False, "command"),
        ("post", "hid", False),
    ]
