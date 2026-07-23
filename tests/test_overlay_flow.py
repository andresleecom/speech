from pathlib import Path
import os
import sys
import types

import winwhisper.overlay as overlay_module
import winwhisper.main as main_module
import pytest
from winwhisper.config import Settings
from winwhisper.config import load_settings, save_settings
from winwhisper.focus import ScreenPoint
from winwhisper.hotkey_settings import HotkeyConfigurationError
from winwhisper.hotkeys import HotkeyActivationResult
from winwhisper.macos_permissions import (
    MacOSPermissionSnapshot,
    PermissionState,
    PermissionStatus,
)
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
        self.audio_input_device = kwargs.get("audio_input_device")

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

    def set_audio_input_device(self, value) -> None:
        if self.recording:
            raise RuntimeError("Stop dictation before changing the microphone.")
        self.audio_input_device = value


class FakeMicrophoneTest:
    instances: list["FakeMicrophoneTest"] = []

    def __init__(self, audio_input_device) -> None:
        self.audio_input_device = audio_input_device
        self.started = False
        self.stopped = False
        self.peak_level = 0.0
        self.instances.append(self)

    def start(self) -> None:
        self.started = True

    def stop(self) -> float:
        self.stopped = True
        return self.peak_level

    def current_level(self) -> float:
        return self.peak_level


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

    def refresh_menu(self) -> None:
        return None


class FakeHotkeys:
    instances: list["FakeHotkeys"] = []
    fail_next_start = False
    fail_stopped_manager_start = False

    def __init__(self, hotkeys: dict[str, str], on_hotkey) -> None:
        self.hotkeys = dict(hotkeys)
        self.on_hotkey = on_hotkey
        self.started = False
        self.stopped = False
        self.instances.append(self)

    def start(self) -> HotkeyActivationResult:
        self.started = True
        if self.stopped and type(self).fail_stopped_manager_start:
            type(self).fail_stopped_manager_start = False
            return HotkeyActivationResult(
                active=(),
                failed=tuple(self.hotkeys.values()),
            )
        if type(self).fail_next_start:
            type(self).fail_next_start = False
            return HotkeyActivationResult(
                active=(),
                failed=tuple(self.hotkeys.values()),
            )
        return HotkeyActivationResult(
            active=tuple(self.hotkeys.values()),
            failed=(),
        )

    def stop(self) -> None:
        self.stopped = True

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


class FakeHotkeySettingsWindow:
    instances: list["FakeHotkeySettingsWindow"] = []

    def __init__(self) -> None:
        self.shown_with = None
        self.instances.append(self)

    def show(self, hotkeys, on_save, language_favorites) -> None:
        self.shown_with = (dict(hotkeys), on_save, list(language_favorites))


class FakeLanguageSettingsWindow:
    instances: list["FakeLanguageSettingsWindow"] = []

    def __init__(self) -> None:
        self.shown_with = None
        self.instances.append(self)

    def show(self, language_mode, language_favorites, on_save) -> None:
        self.shown_with = (language_mode, list(language_favorites), on_save)


class FakePermissionSetupWindow:
    def __init__(self) -> None:
        self.show_count = 0

    def show(self) -> None:
        self.show_count += 1


def permission_snapshot(
    microphone=PermissionState.GRANTED,
    input_monitoring=PermissionState.GRANTED,
    accessibility=PermissionState.GRANTED,
) -> MacOSPermissionSnapshot:
    return MacOSPermissionSnapshot(
        PermissionStatus(microphone),
        PermissionStatus(input_monitoring),
        PermissionStatus(accessibility),
    )


class ImmediateThread:
    def __init__(self, target, args=(), **kwargs) -> None:
        self.target = target
        self.args = args

    def start(self) -> None:
        self.target(*self.args)


class DeferredThread:
    instances: list["DeferredThread"] = []

    def __init__(self, target, args=(), **kwargs) -> None:
        self.target = target
        self.args = args
        self.instances.append(self)

    def start(self) -> None:
        return None


def make_controller(
    monkeypatch,
    tmp_path,
    restored,
    inserted,
    transcription_text="hola mundo",
) -> AppController:
    FakeOverlay.instances.clear()
    FakeHotkeys.instances.clear()
    FakeMicrophoneTest.instances.clear()
    FakeHotkeys.fail_next_start = False
    FakeHotkeys.fail_stopped_manager_start = False
    FakeTranscriber.text = transcription_text
    # Flow tests assert Windows paste semantics; pin the platform so they stay
    # deterministic on the macOS/Linux CI runners.
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("WINWHISPER_APPDATA_DIR", str(tmp_path))
    monkeypatch.setattr(main_module, "Recorder", FakeRecorder)
    monkeypatch.setattr(main_module, "MicrophoneTest", FakeMicrophoneTest)
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


def test_saving_hotkeys_rebinds_running_manager_and_persists(monkeypatch, tmp_path):
    controller = make_controller(monkeypatch, tmp_path, [], [])
    original_manager = controller.hotkeys
    selected_hotkeys = {"toggle_recording": "Windows + Shift + F8"}
    expected_hotkeys = {"toggle_recording": "<shift>+<cmd>+<f8>"}

    controller.set_hotkeys(selected_hotkeys)

    assert original_manager.stopped is True
    assert controller.hotkeys is FakeHotkeys.instances[-1]
    assert controller.hotkeys is not original_manager
    assert controller.hotkeys.started is True
    assert controller.settings.hotkeys == expected_hotkeys
    assert load_settings().hotkeys == expected_hotkeys


def test_duplicate_hotkeys_do_not_replace_running_manager(monkeypatch, tmp_path):
    controller = make_controller(monkeypatch, tmp_path, [], [])
    original_manager = controller.hotkeys

    with pytest.raises(HotkeyConfigurationError, match="same shortcut"):
        controller.set_hotkeys(
            {
                "toggle_recording": "Ctrl + Alt + Space",
                "force_english": "Alt + Ctrl + Space",
            }
        )

    assert controller.hotkeys is original_manager
    assert original_manager.stopped is False
    assert FakeHotkeys.instances == [original_manager]


def test_registration_conflict_rolls_back_to_previous_hotkeys(monkeypatch, tmp_path):
    controller = make_controller(monkeypatch, tmp_path, [], [])
    original_manager = controller.hotkeys
    original_settings = dict(controller.settings.hotkeys)
    FakeHotkeys.fail_next_start = True

    with pytest.raises(HotkeyConfigurationError, match="another application"):
        controller.set_hotkeys({"toggle_recording": "Ctrl + Shift + F8"})

    failed_manager = FakeHotkeys.instances[1]
    assert failed_manager.stopped is True
    assert controller.hotkeys is original_manager
    assert original_manager.started is True
    assert controller.settings.hotkeys == original_settings


def test_save_failure_rolls_back_to_previous_hotkeys(monkeypatch, tmp_path):
    controller = make_controller(monkeypatch, tmp_path, [], [])
    original_manager = controller.hotkeys
    original_settings = dict(controller.settings.hotkeys)

    def fail_save(settings):
        raise OSError("disk full")

    monkeypatch.setattr(main_module, "save_settings", fail_save)

    with pytest.raises(HotkeyConfigurationError, match="could not be saved"):
        controller.set_hotkeys({"toggle_recording": "Ctrl + Shift + F8"})

    failed_manager = FakeHotkeys.instances[1]
    assert failed_manager.stopped is True
    assert controller.hotkeys is original_manager
    assert original_manager.started is True
    assert controller.settings.hotkeys == original_settings


def test_failed_rollback_is_reported_to_settings_window(monkeypatch, tmp_path):
    controller = make_controller(monkeypatch, tmp_path, [], [])
    FakeHotkeys.fail_next_start = True
    FakeHotkeys.fail_stopped_manager_start = True

    with pytest.raises(HotkeyConfigurationError, match="could not be restored"):
        controller.set_hotkeys({"toggle_recording": "Ctrl + Shift + F8"})


def test_controller_opens_hotkey_window_with_live_save_callback(monkeypatch, tmp_path):
    FakeHotkeySettingsWindow.instances.clear()
    monkeypatch.setattr(
        main_module,
        "HotkeySettingsWindow",
        FakeHotkeySettingsWindow,
        raising=False,
    )
    controller = make_controller(monkeypatch, tmp_path, [], [])

    controller.open_hotkey_settings()

    window = FakeHotkeySettingsWindow.instances[-1]
    hotkeys, on_save, language_favorites = window.shown_with
    assert hotkeys == controller.settings.hotkeys
    assert on_save == controller.set_hotkeys
    assert language_favorites == ["en", "es", None]


def test_controller_opens_language_window_with_live_save_callback(monkeypatch, tmp_path):
    FakeLanguageSettingsWindow.instances.clear()
    monkeypatch.setattr(
        main_module,
        "LanguageSettingsWindow",
        FakeLanguageSettingsWindow,
        raising=False,
    )
    controller = make_controller(monkeypatch, tmp_path, [], [])

    controller.open_language_settings()

    window = FakeLanguageSettingsWindow.instances[-1]
    language_mode, language_favorites, on_save = window.shown_with
    assert language_mode == "es"
    assert language_favorites == ["en", "es", None]
    assert on_save == controller.set_language_preferences


def test_controller_persists_selected_catalog_language(monkeypatch, tmp_path):
    controller = make_controller(monkeypatch, tmp_path, [], [])

    controller.set_language_mode("French (fr)")
    controller.set_language_mode("not-a-language")

    assert controller.settings.language_mode == "fr"
    assert load_settings().language_mode == "fr"


def test_controller_persists_favorites_and_routes_quick_language_actions(
    monkeypatch, tmp_path
):
    controller = make_controller(monkeypatch, tmp_path, [], [])
    toggles = []
    monkeypatch.setattr(controller, "toggle", toggles.append)

    controller.set_language_preferences("Japanese", ["French", "Japanese", None])
    controller.on_hotkey("force_en")
    controller.on_hotkey("force_es")
    controller.on_hotkey("force_language_3")

    assert controller.settings.language_mode == "ja"
    assert controller.settings.language_favorites == ["fr", "ja", None]
    assert load_settings().language_favorites == ["fr", "ja", None]
    assert toggles == ["fr", "ja"]
    assert controller.tray.notifications[-1][1].startswith("Set Favorite 3")


def test_controller_persists_input_device_and_runs_microphone_test(monkeypatch, tmp_path):
    controller = make_controller(monkeypatch, tmp_path, [], [])

    controller.set_audio_input_device(3)
    controller.start_microphone_test()
    microphone_test = FakeMicrophoneTest.instances[-1]
    microphone_test.peak_level = 0.4
    controller.stop_from_overlay()

    assert controller.settings.audio_input_device == 3
    assert controller.recorder.audio_input_device == 3
    assert load_settings().audio_input_device == 3
    assert microphone_test.started is True
    assert microphone_test.stopped is True
    assert FakeOverlay.instances[0].events[-2:] == [
        "show:ScreenPoint(x=240, y=320)",
        "hide",
    ]
    assert controller.tray.notifications[-1][1] == "Microphone test complete. Signal detected."


def test_controller_cannot_change_microphone_during_microphone_test(monkeypatch, tmp_path):
    controller = make_controller(monkeypatch, tmp_path, [], [])
    controller.start_microphone_test()

    with pytest.raises(RuntimeError, match="Stop microphone capture"):
        controller.set_audio_input_device(2)

    controller.stop_from_overlay()


def test_controller_reports_missing_microphone_signal(monkeypatch, tmp_path):
    controller = make_controller(monkeypatch, tmp_path, [], [])
    controller.start_microphone_test()

    controller._stop_microphone_test(completed=True)

    assert controller.tray.notifications[-1][1].startswith("No sound detected")


def test_opening_advanced_settings_does_not_overwrite_external_edit(
    monkeypatch, tmp_path
):
    controller = make_controller(monkeypatch, tmp_path, [], [])
    edited_hotkeys = {"toggle_recording": "<ctrl>+<shift>+<f9>"}
    save_settings(Settings(hotkeys=edited_hotkeys))
    opened = []
    monkeypatch.setattr(main_module, "_open_path", opened.append)

    controller.open_settings_file()

    assert opened == [tmp_path / "settings.json"]
    assert load_settings().hotkeys == edited_hotkeys


def test_startup_surfaces_saved_hotkey_registration_conflict(monkeypatch, tmp_path):
    controller = make_controller(monkeypatch, tmp_path, [], [])
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        main_module, "get_permission_snapshot", permission_snapshot
    )
    FakeHotkeys.fail_next_start = True

    controller.run()

    assert any(
        "could not be registered" in message.lower()
        for _title, message in controller.tray.notifications
    )


def test_startup_surfaces_missing_input_monitoring(monkeypatch, tmp_path):
    controller = make_controller(monkeypatch, tmp_path, [], [])
    controller.hotkeys.input_monitoring_missing = True

    controller.run()

    assert any(
        "input monitoring" in message.lower()
        for _title, message in controller.tray.notifications
    )


def test_macos_startup_gates_hotkeys_and_shows_permission_assistant(
    monkeypatch, tmp_path
):
    controller = make_controller(monkeypatch, tmp_path, [], [])
    controller.permission_setup_window = FakePermissionSetupWindow()
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        main_module,
        "get_permission_snapshot",
        lambda: permission_snapshot(
            input_monitoring=PermissionState.MISSING,
            accessibility=PermissionState.MISSING,
        ),
    )

    controller.run()

    assert controller.hotkeys.started is False
    assert controller.permission_setup_window.show_count == 1
    assert any(
        "quit and reopen" in message.lower()
        for _title, message in controller.tray.notifications
    )


def test_macos_startup_starts_hotkeys_only_when_permissions_are_ready(
    monkeypatch, tmp_path
):
    controller = make_controller(monkeypatch, tmp_path, [], [])
    controller.permission_setup_window = FakePermissionSetupWindow()
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        main_module, "get_permission_snapshot", permission_snapshot
    )

    controller.run()

    assert controller.hotkeys.started is True
    assert controller.permission_setup_window.show_count == 0


def test_macos_recording_and_test_are_gated_by_microphone_permission(
    monkeypatch, tmp_path
):
    controller = make_controller(monkeypatch, tmp_path, [], [])
    controller.permission_setup_window = FakePermissionSetupWindow()
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        main_module,
        "get_permission_snapshot",
        lambda: permission_snapshot(microphone=PermissionState.DENIED),
    )

    controller.toggle()
    with pytest.raises(RuntimeError, match="Microphone permission is not ready"):
        controller.start_microphone_test()

    assert controller.recorder.is_recording() is False
    assert FakeMicrophoneTest.instances == []
    assert controller.permission_setup_window.show_count == 2
    assert any(
        "microphone permission is not ready" in message.lower()
        for _title, message in controller.tray.notifications
    )


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


def test_failed_focus_restore_skips_paste(monkeypatch, tmp_path):
    restored: list[int | None] = []
    copied: list[str] = []
    inserted: list[tuple[str, str]] = []
    controller = make_controller(monkeypatch, tmp_path, restored, inserted)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        main_module,
        "restore_foreground_window",
        lambda hwnd: restored.append(hwnd) or False,
    )
    monkeypatch.setattr(
        main_module,
        "copy_text_to_clipboard",
        lambda text: copied.append(text) or True,
        raising=False,
    )

    controller.toggle()
    controller.toggle()

    assert restored == [777]
    assert copied == ["Hola mundo"]
    assert inserted == []
    assert controller.tray.notifications == [
        ("Speech", "Automatic paste failed. Try Ctrl+V.")
    ]


def test_failed_linux_focus_restore_reports_clipboard_failure(monkeypatch, tmp_path):
    inserted: list[tuple[str, str]] = []
    controller = make_controller(monkeypatch, tmp_path, [], inserted)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(main_module, "restore_foreground_window", lambda _hwnd: False)
    monkeypatch.setattr(main_module, "copy_text_to_clipboard", lambda _text: False)

    controller.toggle()
    controller.toggle()

    assert inserted == []
    assert controller.tray.notifications == [
        (
            "Speech",
            "Automatic paste failed, and the transcription could not be copied.",
        )
    ]


def test_failed_windows_focus_restore_still_attempts_paste(monkeypatch, tmp_path):
    inserted: list[tuple[str, str]] = []
    controller = make_controller(monkeypatch, tmp_path, [], inserted)
    monkeypatch.setattr(main_module, "restore_foreground_window", lambda _hwnd: False)

    controller.toggle()
    controller.toggle()

    assert inserted == [("Hola mundo", "ctrl_v")]


def test_empty_transcription_notifies_without_pasting(monkeypatch, tmp_path):
    inserted: list[str] = []
    controller = make_controller(monkeypatch, tmp_path, [], inserted, transcription_text="")

    controller.toggle()
    controller.toggle()

    assert inserted == []
    assert controller.tray.notifications == [("Speech", "No speech detected")]


@pytest.mark.parametrize(
    ("platform", "expected_message"),
    [
        (
            "linux",
            "Still transcribing… first run and local inference can take longer.",
        ),
        (
            "darwin",
            "Still transcribing… first run or antivirus scanning can take longer.",
        ),
        (
            "win32",
            "Still transcribing… first run or antivirus scanning can take longer.",
        ),
    ],
)
def test_slow_transcription_message_changes_only_on_linux(
    monkeypatch,
    tmp_path,
    platform,
    expected_message,
):
    controller = make_controller(monkeypatch, tmp_path, [], [])
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(
        main_module, "get_permission_snapshot", permission_snapshot
    )
    monkeypatch.setattr(main_module, "SLOW_TRANSCRIPTION_NOTIFY_SECONDS", 0)
    monkeypatch.setattr(main_module, "_RealThread", ImmediateThread)

    controller.toggle()
    controller.toggle()

    assert ("Speech", expected_message) in controller.tray.notifications


def test_blocked_microphone_stop_triggers_hard_exit_boundary(monkeypatch, tmp_path):
    controller = make_controller(monkeypatch, tmp_path, [], [])
    DeferredThread.instances.clear()
    exit_codes = []
    monkeypatch.setattr(main_module.threading, "Thread", DeferredThread)
    monkeypatch.setattr(main_module, "_RealThread", ImmediateThread)
    monkeypatch.setattr(main_module, "MICROPHONE_STOP_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(main_module, "_hard_exit", exit_codes.append)

    controller.toggle()
    controller.toggle()

    worker = DeferredThread.instances[-1]
    stop_complete = worker.args[1]
    assert stop_complete is controller._microphone_stop_complete
    assert stop_complete.is_set() is False
    assert exit_codes == [70]
    assert controller.tray.notifications[-1] == (
        "Speech",
        "Microphone shutdown is stuck. Speech must close to release it.",
    )


def test_completed_microphone_stop_never_times_out_during_transcription(
    monkeypatch,
    tmp_path,
):
    controller = make_controller(monkeypatch, tmp_path, [], [])
    exit_codes = []
    monkeypatch.setattr(main_module, "MICROPHONE_STOP_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(main_module, "_RealThread", ImmediateThread)
    monkeypatch.setattr(main_module, "_hard_exit", exit_codes.append)
    monkeypatch.setattr(
        controller,
        "_start_slow_transcription_watcher",
        lambda cancel: None,
    )

    original_transcribe = controller.transcriber.transcribe

    def slow_transcribe(audio_path, language_mode):
        stop_complete = controller._microphone_stop_complete
        assert stop_complete is not None
        assert stop_complete.is_set() is True
        controller._watch_microphone_stop(stop_complete)
        return original_transcribe(audio_path, language_mode)

    monkeypatch.setattr(controller.transcriber, "transcribe", slow_transcribe)

    controller.toggle()
    controller.toggle()

    assert exit_codes == []


def test_shutdown_does_not_log_stopped_with_unresolved_microphone_stop(
    monkeypatch,
    tmp_path,
    caplog,
):
    controller = make_controller(monkeypatch, tmp_path, [], [])
    exit_codes = []
    controller._microphone_stop_complete = main_module.threading.Event()
    monkeypatch.setattr(main_module, "MICROPHONE_STOP_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(main_module, "_hard_exit", exit_codes.append)

    with caplog.at_level("INFO"):
        controller.stop()

    assert exit_codes == [70]
    assert "Speech stopped." not in caplog.text


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


def test_overlay_run_never_touches_tk_on_macos(monkeypatch):
    """Regression: creating a Tk window on a worker thread aborts the whole
    process on macOS (NSException in Tk). The darwin path must consume
    commands without importing tkinter and exit on stop."""
    calls = []

    def forbidden_import(name, *args, **kwargs):
        if name == "tkinter":
            raise AssertionError("tkinter must not be imported on macOS")
        return real_import(name, *args, **kwargs)

    import builtins

    real_import = builtins.__import__
    monkeypatch.setattr(overlay_module.os, "name", "posix")
    monkeypatch.setattr(overlay_module.sys, "platform", "darwin")
    monkeypatch.setattr(builtins, "__import__", forbidden_import)

    overlay = overlay_module.RecordingOverlay(lambda: calls.append("stop"))
    overlay._commands.put(overlay_module.OverlayCommand("show", None))
    overlay._commands.put(overlay_module.OverlayCommand("transcribing"))
    overlay._commands.put(overlay_module.OverlayCommand("stop"))

    overlay._run()  # must return promptly without touching Tk

    assert overlay._commands.empty()


@pytest.mark.skipif(os.name != "nt", reason="Native overlay is Windows-only")
def test_native_overlay_premultiplies_rgba_for_layered_window():
    from PIL import Image

    from winwhisper.native_overlay import rgba_to_bgra_premultiplied

    image = Image.new("RGBA", (1, 1), (100, 50, 200, 128))

    assert rgba_to_bgra_premultiplied(image) == bytes((100, 25, 50, 128))
