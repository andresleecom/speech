import sys
import types

import winwhisper.hotkey_settings_window as window_module
from winwhisper.hotkey_settings_window import HotkeySettingsWindow


class ImmediateThread:
    def __init__(self, target, args=(), **kwargs) -> None:
        self.target = target
        self.args = args

    def start(self) -> None:
        self.target(*self.args)


def test_windows_editor_uses_tk_adapter_without_blocking_caller(monkeypatch):
    calls = []
    hotkeys = {"toggle_recording": "<ctrl>+<alt>+<space>"}
    on_save = lambda values: None
    monkeypatch.setattr(window_module.sys, "platform", "win32")
    monkeypatch.setattr(window_module.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(
        window_module,
        "_run_tk_dialog",
        lambda values, callback, platform, language_favorites=None: calls.append(
            (values, callback, platform, language_favorites)
        ),
    )

    HotkeySettingsWindow().show(hotkeys, on_save)

    assert calls == [(hotkeys, on_save, "win32", None)]


def test_macos_editor_is_scheduled_on_appkit_main_queue(monkeypatch):
    calls = []
    hotkeys = {"toggle_recording": "<ctrl>+<alt>+<space>"}
    on_save = lambda values: None

    class FakeMainQueue:
        def addOperationWithBlock_(self, operation) -> None:
            operation()

    class FakeOperationQueue:
        @classmethod
        def mainQueue(cls):
            return FakeMainQueue()

    foundation = types.SimpleNamespace(NSOperationQueue=FakeOperationQueue)
    monkeypatch.setitem(sys.modules, "Foundation", foundation)
    monkeypatch.setattr(window_module.sys, "platform", "darwin")
    monkeypatch.setattr(
        window_module,
        "_run_macos_dialog",
        lambda values, callback, language_favorites=None: calls.append(
            (values, callback, language_favorites)
        ),
    )

    HotkeySettingsWindow().show(hotkeys, on_save)

    assert calls == [(hotkeys, on_save, None)]


class FakePhotoImage:
    def __init__(self, image) -> None:
        self.image = image


class FakeVariable:
    def __init__(self, value="") -> None:
        self._value = value

    def get(self):
        return self._value

    def set(self, value) -> None:
        self._value = value


class FakeWidget:
    def __init__(self, master=None, **options) -> None:
        self.master = master
        self.options = dict(options)
        self.grid_options = None
        self.pack_options = None
        self.children = []
        if isinstance(master, FakeWidget):
            master.children.append(self)

    def grid(self, **options) -> None:
        self.grid_options = options

    def pack(self, **options) -> None:
        self.pack_options = options

    def configure(self, **options) -> None:
        self.options.update(options)

    def bind(self, sequence, handler) -> None:
        return None

    def focus_set(self) -> None:
        return None


class FakeRoot(FakeWidget):
    def __init__(self, **options) -> None:
        super().__init__(None, **options)
        self.window_title = None
        self.icon_photos = []
        self.scheduled = []
        self.destroyed = False

    def title(self, text) -> None:
        self.window_title = text

    def resizable(self, *args) -> None:
        return None

    def iconphoto(self, default, photo) -> None:
        self.icon_photos.append((default, photo))

    def protocol(self, name, handler) -> None:
        return None

    def after(self, delay, callback) -> None:
        self.scheduled.append((delay, callback))

    def update_idletasks(self) -> None:
        return None

    def winfo_screenwidth(self) -> int:
        return 1920

    def winfo_screenheight(self) -> int:
        return 1080

    def winfo_width(self) -> int:
        return 600

    def winfo_height(self) -> int:
        return 400

    def geometry(self, value) -> None:
        self.geometry_value = value

    def lift(self) -> None:
        return None

    def attributes(self, *args) -> None:
        return None

    def mainloop(self) -> None:
        return None

    def destroy(self) -> None:
        self.destroyed = True


def install_fake_tk(monkeypatch):
    """Run a Tk dialog headless and hand back the roots it created."""
    import PIL

    roots = []

    class Root(FakeRoot):
        def __init__(self, **options) -> None:
            super().__init__(**options)
            roots.append(self)

    ttk = types.SimpleNamespace(Combobox=FakeWidget)
    tk = types.SimpleNamespace(
        Tk=Root,
        Frame=FakeWidget,
        Label=FakeWidget,
        Button=FakeWidget,
        StringVar=FakeVariable,
        ttk=ttk,
    )
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", ttk)
    monkeypatch.setattr(
        PIL,
        "ImageTk",
        types.SimpleNamespace(PhotoImage=FakePhotoImage),
        raising=False,
    )
    return roots


def find_widgets(widget):
    """Flatten the fake widget tree so a test can look for one row."""
    found = [widget]
    for child in widget.children:
        found.extend(find_widgets(child))
    return found


def test_hotkey_dialog_uses_the_app_icon_and_a_hyphen_title(monkeypatch):
    roots = install_fake_tk(monkeypatch)

    window_module._run_tk_dialog(
        {"toggle_recording": "<ctrl>+<alt>+<space>"},
        lambda values: None,
        platform="win32",
    )

    root = roots[0]
    assert root.window_title == "Speech Settings - Hotkeys"
    assert len(root.icon_photos) == 1
    default, photo = root.icon_photos[0]
    assert default is True
    assert photo.image.size == (64, 64)


def test_full_width_rows_span_the_record_column(monkeypatch):
    from winwhisper.hotkey_actions import HOTKEY_ACTIONS

    roots = install_fake_tk(monkeypatch)

    window_module._run_tk_dialog({}, lambda values: None, platform="win32")

    widgets = find_widgets(roots[0])
    spanning_rows = {
        widget.grid_options["row"]
        for widget in widgets
        if widget.grid_options and widget.grid_options.get("columnspan") == 3
    }
    # Subtitle, then the status line and the buttons under the action rows.
    assert 1 in spanning_rows
    assert len(HOTKEY_ACTIONS) + 2 in spanning_rows
    assert len(HOTKEY_ACTIONS) + 3 in spanning_rows
    assert not any(
        widget.grid_options.get("columnspan") == 2
        for widget in widgets
        if widget.grid_options
    )


def status_and_record_widgets(root):
    widgets = find_widgets(root)
    status_label = next(
        widget
        for widget in widgets
        if widget.grid_options
        and widget.grid_options.get("columnspan") == 3
        and "textvariable" in widget.options
    )
    record_button = next(
        widget
        for widget in widgets
        if widget.options.get("text") == "Record" and "command" in widget.options
    )
    return status_label, record_button


def test_recording_hint_is_neutral_grey_not_an_error(monkeypatch):
    class FakeCapture:
        def __init__(self, on_captured, on_cancelled) -> None:
            self.on_cancelled = on_cancelled

        def start(self) -> None:
            return None

        def cancel(self) -> None:
            return None

    import winwhisper.mouse_capture as mouse_capture

    monkeypatch.setattr(mouse_capture, "MouseCapture", FakeCapture)
    roots = install_fake_tk(monkeypatch)

    window_module._run_tk_dialog({}, lambda values: None, platform="win32")

    status_label, record_button = status_and_record_widgets(roots[0])
    record_button.options["command"]()

    assert status_label.options["textvariable"].get().startswith("Press a mouse button")
    assert status_label.options["fg"] == window_module._MUTED


def test_capture_failure_keeps_the_accent_colour(monkeypatch):
    class BrokenCapture:
        def __init__(self, on_captured, on_cancelled) -> None:
            return None

        def start(self) -> None:
            raise RuntimeError("no mouse listener")

    import winwhisper.mouse_capture as mouse_capture

    monkeypatch.setattr(mouse_capture, "MouseCapture", BrokenCapture)
    roots = install_fake_tk(monkeypatch)

    window_module._run_tk_dialog({}, lambda values: None, platform="win32")

    status_label, record_button = status_and_record_widgets(roots[0])
    record_button.options["command"]()

    assert status_label.options["textvariable"].get() == (
        "Mouse capture is unavailable on this system."
    )
    assert status_label.options["fg"] == window_module._ACCENT
