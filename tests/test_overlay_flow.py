from pathlib import Path
import os
import sys
import types

import winwhisper.overlay as overlay_module
import winwhisper.main as main_module
import pytest
from winwhisper.config import Settings
from winwhisper.focus import ScreenPoint
from winwhisper.main import AppController
from winwhisper.overlay import (
    dragged_overlay_position,
    is_stop_button_point,
    position_near_anchor,
    render_orb_frame,
    sonar_ring_visuals,
    _tk_monitor_work_area,
    _tk_virtual_screen_bounds,
)
from winwhisper.transcriber import TranscriptionResult


class FakeRecorder:
    def __init__(self, *args, **kwargs) -> None:
        self.recording = False

    def start_recording(self) -> None:
        self.recording = True

    def stop_recording(self) -> Path | None:
        if not self.recording:
            return None
        self.recording = False
        return Path("fake-recording.wav")

    def is_recording(self) -> bool:
        return self.recording

    def current_level(self) -> float:
        return 0.0


class FakeTranscriber:
    text = "hola mundo"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._loaded = False

    def is_model_loaded(self) -> bool:
        return self._loaded

    def ensure_model_loaded(self) -> None:
        self._loaded = True

    def transcribe(self, audio_path: Path, language_mode: str) -> TranscriptionResult:
        self._loaded = True
        return TranscriptionResult(
            text=self.text,
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

    def reset_state(self) -> None:
        return None

    def reset_trigger_state(self) -> None:
        return None


class FakeOverlay:
    instances: list["FakeOverlay"] = []

    def __init__(self, on_stop, level_provider=None) -> None:
        self.on_stop = on_stop
        self.level_provider = level_provider
        self.events: list[str] = []
        self.instances.append(self)

    def show(self, anchor=None) -> None:
        self.events.append(f"show:{anchor!r}")

    def hide(self) -> None:
        self.events.append("hide")

    def show_transcribing(self) -> None:
        self.events.append("transcribing")

    def stop(self) -> None:
        self.events.append("stop")


class ImmediateThread:
    def __init__(self, target, args=(), **kwargs) -> None:
        self.target = target
        self.args = args

    def start(self) -> None:
        self.target(*self.args)


def make_controller(
    monkeypatch,
    tmp_path,
    restored,
    inserted,
    transcription_text="hola mundo",
) -> AppController:
    FakeOverlay.instances.clear()
    FakeTranscriber.text = transcription_text
    # Flow tests assert Windows paste semantics; pin the platform so they stay
    # deterministic on the macOS/Linux CI runners.
    monkeypatch.setattr(sys, "platform", "win32")
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
    assert FakeOverlay.instances[0].events == [
        "show:ScreenPoint(x=240, y=320)",
        "transcribing",
        "hide",
    ]


def test_hotkey_stop_restores_target_window_before_paste(monkeypatch, tmp_path):
    restored: list[int | None] = []
    inserted: list[str] = []
    controller = make_controller(monkeypatch, tmp_path, restored, inserted)

    controller.toggle()
    controller.toggle()

    assert restored == [777]
    assert inserted == [("Hola mundo", "ctrl_v")]
    assert FakeOverlay.instances[0].events == [
        "show:ScreenPoint(x=240, y=320)",
        "transcribing",
        "hide",
    ]


def test_empty_transcription_notifies_without_pasting(monkeypatch, tmp_path):
    inserted: list[str] = []
    controller = make_controller(monkeypatch, tmp_path, [], inserted, transcription_text="")

    controller.toggle()
    controller.toggle()

    assert inserted == []
    assert controller.tray.notifications == [("Speech", "No speech detected")]


def test_late_overlay_stop_does_not_start_new_recording(monkeypatch, tmp_path):
    controller = make_controller(monkeypatch, tmp_path, [], [])

    controller.stop_from_overlay()

    assert controller.recorder.is_recording() is False
    assert FakeOverlay.instances[0].events == ["hide"]


def test_late_max_duration_stop_does_not_start_new_recording(monkeypatch, tmp_path):
    controller = make_controller(monkeypatch, tmp_path, [], [])

    controller._handle_max_recording_duration()

    assert controller.recorder.is_recording() is False
    assert controller.tray.notifications == []
    assert FakeOverlay.instances[0].events == []


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


def test_position_near_anchor_respects_negative_origin():
    # Secondary monitor to the left of primary (virtual coords can be negative).
    x, y = position_near_anchor(
        ScreenPoint(-400, 200),
        screen_width=1920,
        screen_height=1080,
        origin_x=-1920,
        origin_y=0,
    )
    assert -1920 + 24 <= x <= -24
    assert 24 <= y <= 1080 - 152 - 24


def test_position_near_anchor_keeps_overlay_inside_screen():
    assert position_near_anchor(
        ScreenPoint(1_900, 1_000),
        screen_width=1_920,
        screen_height=1_080,
        width=168,
        height=58,
    ) == (1_714, 971)


def test_position_near_anchor_prefers_right_side_of_cursor():
    assert position_near_anchor(
        ScreenPoint(240, 320),
        screen_width=1_920,
        screen_height=1_080,
        width=168,
        height=58,
    ) == (258, 291)


def test_position_near_anchor_without_anchor_stays_on_screen():
    x, y = position_near_anchor(
        None,
        screen_width=1_920,
        screen_height=1_080,
        width=168,
        height=58,
    )
    assert 24 <= x <= 1_920 - 168 - 24
    assert 24 <= y <= 1_080 - 58 - 24


def test_sonar_ring_visuals_grow_with_voice_level():
    quiet = sonar_ring_visuals(0.0, phase=0, count=3)
    loud = sonar_ring_visuals(0.9, phase=0, count=3)

    assert len(quiet) == 3
    assert len(loud) == 3
    assert max(scale for scale, opacity in loud) > max(
        scale for scale, opacity in quiet
    )


def test_sonar_ring_visuals_shift_with_phase():
    first = sonar_ring_visuals(0.5, phase=0, count=3)
    second = sonar_ring_visuals(0.5, phase=1, count=3)

    assert first != second


def test_dragged_overlay_position_follows_pointer_inside_screen():
    assert dragged_overlay_position(
        origin=ScreenPoint(258, 291),
        press=ScreenPoint(300, 310),
        pointer=ScreenPoint(360, 340),
        screen_width=1_920,
        screen_height=1_080,
        width=188,
        height=54,
    ) == (318, 321)


def test_dragged_overlay_position_stays_inside_screen():
    assert dragged_overlay_position(
        origin=ScreenPoint(10, 10),
        press=ScreenPoint(20, 20),
        pointer=ScreenPoint(-200, -200),
        screen_width=1_920,
        screen_height=1_080,
        width=188,
        height=54,
    ) == (24, 24)


def test_stop_button_hit_area_is_limited_to_red_control():
    assert is_stop_button_point(76, 76) is True
    assert is_stop_button_point(20, 20) is False


def test_render_orb_frame_has_antialiased_transparent_edges():
    image = render_orb_frame("recording", level=0.5, phase=4)

    assert image.mode == "RGBA"
    assert image.size == (152, 152)
    alpha_histogram = image.getchannel("A").histogram()
    assert alpha_histogram[0] > 0
    assert sum(alpha_histogram[1:255]) > 0


def test_render_orb_frame_keeps_stop_control_crisp():
    image = render_orb_frame("recording", level=0.0, phase=0)

    red_r, red_g, red_b, red_alpha = image.getpixel((76, 56))
    glyph_r, glyph_g, glyph_b, glyph_alpha = image.getpixel((76, 76))

    assert red_alpha == 255
    assert red_r > 190
    assert red_g < 90
    assert red_b < 90
    assert glyph_alpha == 255
    assert glyph_r > 240
    assert glyph_g > 240
    assert glyph_b > 240


def test_tk_fallback_uses_native_virtual_screen_bounds(monkeypatch):
    class FakeRoot:
        def winfo_screenwidth(self):
            return 1920

        def winfo_screenheight(self):
            return 1080

    native_overlay = types.SimpleNamespace(
        _monitor_work_area=lambda anchor: (-1920, 0, 1920, 1040),
        _virtual_screen_bounds=lambda: (-1920, 0, 3840, 1080),
    )
    monkeypatch.setattr(overlay_module.os, "name", "nt")
    monkeypatch.setitem(sys.modules, "winwhisper.native_overlay", native_overlay)

    assert _tk_monitor_work_area(FakeRoot(), ScreenPoint(-400, 200)) == (
        -1920,
        0,
        1920,
        1040,
    )
    assert _tk_virtual_screen_bounds(FakeRoot()) == (-1920, 0, 3840, 1080)


@pytest.mark.skipif(os.name != "nt", reason="Native overlay is Windows-only")
def test_native_overlay_premultiplies_rgba_for_layered_window():
    from PIL import Image

    from winwhisper.native_overlay import rgba_to_bgra_premultiplied

    image = Image.new("RGBA", (1, 1), (100, 50, 200, 128))

    assert rgba_to_bgra_premultiplied(image) == bytes((100, 25, 50, 128))
