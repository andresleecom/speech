# Task 01: refresh the audio device table before every open

You are the MAP executor (Grok CLI). Obey HARD RULES. No git. End with ## REPORT.

## Goal
PortAudio freezes the Windows device order at `Pa_Initialize`. When a Bluetooth headset connects or disconnects while Speech runs, the saved microphone name still resolves against the stale table and the app opens the wrong physical device (today: the Beats hands-free mic, 3 s stall, garbage audio) or a dead slot (0 frames). Fix: refresh the table before every sounddevice open when no stream is open, pause the wake listener around hotkey takes so the refresh can run, and bump the version to 0.1.20.

## Context - read these first
- `src/winwhisper/audio_inputs.py`: `list_audio_input_devices`, `resolve_input_device`, `_sounddevice()`, `_use_native_macos_audio()`.
- `src/winwhisper/recorder.py`: `Recorder.start_recording` (calls `list_audio_input_devices()` then `resolve_input_device`), `stop_recording`, `TakeStats`, `MicrophoneTest.start/stop`.
- `src/winwhisper/wake_word_source.py`: `SounddeviceSource.start/stop`.
- `src/winwhisper/main.py`: `toggle()` calls `self.recorder.start_recording()`; `_on_wake_word` pauses the listener before a wake take; `_stop_and_process` resumes it in `finally` only when `_recording_started_by_wake_word`; the `Take timing:` log line.
- Facts measured on this machine: `sd._terminate(); sd._initialize()` takes about 40 ms and must never run while any PortAudio stream is open in the process. `WakeWordListener.pause()`/`resume()` are idempotent.
- Tests: `tests/test_recorder.py` (fake sounddevice), `tests/test_overlay_flow.py` (FakeRecorder, controller harness), `tests/test_wake_word.py`, `tests/test_audio_inputs.py`.

## Scope - you may edit
- `src/winwhisper/audio_inputs.py`, `recorder.py`, `wake_word_source.py`, `main.py`, `pyproject.toml`
- `tests/test_audio_inputs.py`, `tests/test_recorder.py`, `tests/test_overlay_flow.py`, `tests/test_wake_word.py`

## Out of scope - do not touch
- `recorder_mac.py`, `wake_word_source_mac.py`, `tray.py`, `config.py`, `transcriber.py`, docs, installer, workflows.

## Steps
1. `audio_inputs.py`: a process-wide open-stream counter behind a lock with `register_open_stream()` / `unregister_open_stream()`, and `refresh_audio_device_table() -> float | None`: returns `None` on macOS, when the counter is above zero (log at DEBUG why), or on any exception (log WARNING); otherwise calls `sd._terminate()` then `sd._initialize()` and returns the elapsed milliseconds.
2. `recorder.py`: `Recorder.start_recording` and `MicrophoneTest.start` call `refresh_audio_device_table()` before `list_audio_input_devices()`, register the stream right after `stream.start()` succeeds, and unregister in `stop_recording`/`stop` after close and on every open-failure path. Add `refresh_ms: float | None` and `host_api: str` to `TakeStats` (host API of the resolved row, or "default").
3. `wake_word_source.py`: `SounddeviceSource.start` refreshes before listing, registers after start; `stop` unregisters.
4. `main.py`: in `toggle()`, before `start_recording()`, pause the wake listener if one exists (and note it); in `_stop_and_process`'s `finally`, resume whenever a listener exists and `wake_word_enabled` is true (keep the wake-started behaviour working); also resume when the start fails. Add `refresh_ms=%s host_api=%s` to the `Take timing:` line.
5. `pyproject.toml`: version `0.1.20`.
6. Tests: with a fake sounddevice whose `query_devices()` table changes after `_initialize()`, a Recorder take resolves the saved name to the new index; refresh is skipped while another stream is registered; `MicrophoneTest` and `SounddeviceSource` refresh and register/unregister; the controller pauses the listener before a hotkey take and resumes after it (and after a failed start); stats carry `refresh_ms`.

## Verify before reporting
Run: `env -u SSLKEYLOGFILE .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
Run: `env -u SSLKEYLOGFILE .venv/Scripts/python.exe -c "import time; from winwhisper.recorder import Recorder; r=Recorder(on_max_duration=lambda: None); r.set_audio_input_selection('Desktop Microphone (RØDE PodMic','MME',3); r.start_recording(); time.sleep(0.6); p=r.stop_recording(); s=r.last_take_stats(); print(r.last_resolution.index, s.refresh_ms, s.first_block_ms, s.frames, s.host_api); p and p.unlink()"`
Paste both outputs in your REPORT under PROOF.

HARD RULES - violating any of these means your work is discarded:
- NO git commands of any kind (no commit, branch, push, reset, checkout, stash).
- NO dependency changes: no package installs, no lockfile edits, no tool installs.
- Edit ONLY within the scope listed above. If the fix requires touching anything else, STOP and explain in your REPORT instead of doing it.
- If blocked or uncertain, STOP and report - do not improvise around the spec.
- End your output with:
  ## REPORT
  STATUS: done | blocked
  FILES TOUCHED: <list>
  PROOF: <output of the verification commands you were asked to run>
  NOTES: <≤10 lines: decisions made, anything the reviewer must know>
