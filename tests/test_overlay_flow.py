from pathlib import Path

import winwhisper.main as main_module
from winwhisper.config import Settings
from winwhisper.focus import ScreenPoint
from winwhisper.main import AppController
from winwhisper.overlay import position_near_anchor
from winwhisper.transcriber import TranscriptionResult


class FakeRecorder:
    def __init__(self) -> None:
        self.recording = False

    def start_recording(self) -> None:
        self.recording = True

    def stop_recording(self) -> Path:
        self.recording = False
        return Path("fake-recording.wav")

    def is_recording(self) -> bool:
        return self.recording


class FakeTranscriber:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def transcribe(self, audio_path: Path, language_mode: str) -> TranscriptionResult:
        return TranscriptionResult(
            text="hola mundo",
            language="es",
            language_probability=1.0,
            duration=1.0,
            model_size="small",
            device="cpu",
        )


class FakeTray:
    def __init__(self, controller: AppController) -> None:
        self.controller = controller
        self.statuses: list[str] = []
        self.notifications: list[tuple[str, str]] = []

    def run(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def set_status(self, status: str) -> None:
        self.statuses.append(status)

    def notify(self, title: str, message: str) -> None:
        self.notifications.append((title, message))


class FakeHotkeys:
    def __init__(self, hotkeys: dict[str, str], on_hotkey) -> None:
        self.hotkeys = hotkeys
        self.on_hotkey = on_hotkey

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None


class FakeOverlay:
    instances: list["FakeOverlay"] = []

    def __init__(self, on_stop) -> None:
        self.on_stop = on_stop
        self.events: list[str] = []
        self.instances.append(self)

    def show(self, anchor=None) -> None:
        self.events.append(f"show:{anchor!r}")

    def hide(self) -> None:
        self.events.append("hide")

    def stop(self) -> None:
        self.events.append("stop")


class ImmediateThread:
    def __init__(self, target, args=(), **kwargs) -> None:
        self.target = target
        self.args = args

    def start(self) -> None:
        self.target(*self.args)


def make_controller(monkeypatch, tmp_path, restored, inserted) -> AppController:
    FakeOverlay.instances.clear()
    monkeypatch.setenv("WINWHISPER_APPDATA_DIR", str(tmp_path))
    monkeypatch.setattr(main_module, "Recorder", FakeRecorder)
    monkeypatch.setattr(main_module, "Transcriber", FakeTranscriber)
    monkeypatch.setattr(main_module, "TrayApp", FakeTray)
    monkeypatch.setattr(main_module, "HotkeyManager", FakeHotkeys)
    monkeypatch.setattr(main_module, "RecordingOverlay", FakeOverlay)
    monkeypatch.setattr(main_module, "get_foreground_window", lambda: 777)
    monkeypatch.setattr(main_module, "get_window_process_name", lambda hwnd: "notepad.exe")
    monkeypatch.setattr(main_module, "get_cursor_anchor", lambda hwnd: ScreenPoint(240, 320))
    monkeypatch.setattr(
        main_module,
        "restore_foreground_window",
        lambda hwnd: restored.append(hwnd) or True,
    )
    monkeypatch.setattr(
        main_module,
        "insert_text",
        lambda text, shortcut="ctrl_v": inserted.append((text, shortcut)) or True,
    )
    monkeypatch.setattr(main_module.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(AppController, "_beep", lambda self, frequency, duration_ms: None)
    return AppController(Settings(language_mode="es", delete_audio_after_transcription=False))


def test_start_recording_shows_floating_overlay(monkeypatch, tmp_path):
    controller = make_controller(monkeypatch, tmp_path, [], [])

    controller.toggle()

    assert controller.recorder.is_recording() is True
    assert FakeOverlay.instances[0].events == ["show:ScreenPoint(x=240, y=320)"]


def test_overlay_stop_restores_target_window_before_paste(monkeypatch, tmp_path):
    restored: list[int | None] = []
    inserted: list[str] = []
    controller = make_controller(monkeypatch, tmp_path, restored, inserted)

    controller.toggle()
    controller.stop_from_overlay()

    assert restored == [777]
    assert inserted == [("Hola mundo", "ctrl_v")]
    assert FakeOverlay.instances[0].events == ["show:ScreenPoint(x=240, y=320)", "hide"]


def test_hotkey_stop_does_not_force_restore_before_paste(monkeypatch, tmp_path):
    restored: list[int | None] = []
    inserted: list[str] = []
    controller = make_controller(monkeypatch, tmp_path, restored, inserted)

    controller.toggle()
    controller.toggle()

    assert restored == []
    assert inserted == [("Hola mundo", "ctrl_v")]
    assert FakeOverlay.instances[0].events == ["show:ScreenPoint(x=240, y=320)", "hide"]


def test_late_overlay_stop_does_not_start_new_recording(monkeypatch, tmp_path):
    controller = make_controller(monkeypatch, tmp_path, [], [])

    controller.stop_from_overlay()

    assert controller.recorder.is_recording() is False
    assert FakeOverlay.instances[0].events == ["hide"]


def test_windows_terminal_target_uses_ctrl_shift_v(monkeypatch, tmp_path):
    inserted: list[tuple[str, str]] = []
    controller = make_controller(monkeypatch, tmp_path, [], inserted)
    monkeypatch.setattr(
        main_module,
        "get_window_process_name",
        lambda hwnd: "WindowsTerminal.exe",
    )

    controller.toggle()
    controller.toggle()

    assert inserted == [("Hola mundo", "ctrl_shift_v")]


def test_position_near_anchor_keeps_overlay_inside_screen():
    assert position_near_anchor(
        ScreenPoint(1_900, 1_000),
        screen_width=1_920,
        screen_height=1_080,
        width=168,
        height=58,
    ) == (1_714, 924)


def test_position_near_anchor_uses_bottom_right_without_anchor():
    assert position_near_anchor(
        None,
        screen_width=1_920,
        screen_height=1_080,
        width=168,
        height=58,
    ) == (1_728, 998)
