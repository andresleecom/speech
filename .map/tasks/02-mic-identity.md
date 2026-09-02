# Task 02: Stable microphone identity with System Default fallback

You are the MAP executor (Grok CLI). Obey HARD RULES. No git. End with ## REPORT.

## Goal
The saved microphone is identified by name plus host API instead of a bare PortAudio index, is re-resolved at every stream open, and falls back to System Default (never persisted, toasted once per change) when it is missing. Today `settings.json` holds `audio_input_device: 3` while the RØDE PodMic is index 2; every hotkey press fails with PortAudioError and the log shows `NoneType: None` instead of the real error.

## Context - read these first
- `src/winwhisper/audio_inputs.py`: `AudioInputDevice`, `normalize_audio_input_device`, `list_audio_input_devices` (sounddevice rows; macOS via AVFoundation with `uniqueID`), `default_audio_input_device`, `audio_input_device_label`, `macos_audio_capture_device`.
- `src/winwhisper/recorder.py`: `Recorder.start_recording`, `MicrophoneTest`, `_input_stream` (opens the raw index blind), `RecorderError` message at ~line 84-95 drops the PortAudio text.
- `src/winwhisper/wake_word_source.py`: `SounddeviceSource.start` opens the same way.
- `src/winwhisper/config.py`: `Settings.audio_input_device`, `_migrate_audio_input_device`, `save_settings`.
- `src/winwhisper/main.py`: `toggle()` (~line 300-350, catches the recorder error and calls `_handle_error` outside the `except`, which is why the traceback is lost), `set_audio_input_device` (~line 510), the wake listener start/stop helpers (~line 409-449), `_handle_error`.
- `src/winwhisper/tray.py`: `_make_microphone_menu`, `_current_audio_input_device`, the tooltip in `set_status` (~line 320).
- Tests that model these: `tests/test_audio_inputs.py`, `test_recorder.py`, `test_overlay_flow.py` (FakeRecorder), `test_tray.py`, `test_config.py`, `test_wake_word.py`.
- Live facts on this machine: `sd.query_devices()` lists the RØDE as `Desktop Microphone (RØDE PodMic` on MME index 2, DirectSound 12, WASAPI 27, WDM-KS 46; index 3 is not an input; `sd.default.device[0]` is 1 (a UGREEN capture dongle, not a mic).

## Scope - you may edit
- `src/winwhisper/audio_inputs.py`, `config.py`, `recorder.py`, `wake_word_source.py`, `main.py`, `tray.py`
- `tests/test_audio_inputs.py`, `test_config.py`, `test_recorder.py`, `test_overlay_flow.py`, `test_tray.py`, `test_wake_word.py`
- `docs/configuration.md` (Microphone section and settings table only)

## Out of scope - do not touch
- `recorder_mac.py`, `wake_word.py`, `transcriber.py`, overlay files, installer, workflows, `pyproject.toml`, other tests.

## Steps
1. `audio_inputs.py`: add `host_api: str` to `AudioInputDevice` (sounddevice: `query_hostapis(device["hostapi"])["name"]`; macOS: the `uniqueID`). Skip rows whose host API is `Windows WDM-KS`. Add `resolve_input_device(name, host_api, index_hint, devices=None) -> ResolvedInputDevice(index: int | None, label: str, fallback: bool, reason: str)` with this order: exact name+host_api; then any row with the same name that passes `sd.check_input_settings(device=idx, samplerate=16000, channels=1, dtype="int16")` (pass `extra_settings=sd.WasapiSettings(auto_convert=True)` for WASAPI rows); then `None` meaning System Default with `fallback=True` and a human reason. `name is None` means the user chose System Default (not a fallback). Add `input_stream_extra_settings(host_api) -> dict` returning `{"extra_settings": sd.WasapiSettings(auto_convert=True)}` only for `Windows WASAPI`. Keep every existing function working.
2. `config.py`: add `audio_input_device_name: str | None = None` and `audio_input_device_host_api: str | None = None` (strip, empty -> None). Keep `audio_input_device` as an index hint. No sounddevice calls in config.
3. `recorder.py` and `wake_word_source.py`: store the identity (name, host_api, index hint) via a new `set_audio_input_selection(name, host_api, index_hint)` (keep `set_audio_input_device(int)` working as hint-only), call `resolve_input_device` on every open, pass the resolved index plus `input_stream_extra_settings`, expose `last_resolution`. `RecorderError` must include `str(exc)` and the resolved index and label.
4. `main.py`: remove the doubled blank line after the startup log call in `main()` (left by task 01). At startup, if the settings have an index but no name, adopt name+host_api from the live table and save (guard every exception, never raise). `set_audio_input_device(index)` records name+host_api from the live table, saves, and stops/restarts the wake listener if it was running. After each successful start compare `recorder.last_resolution` with the previous one; when `fallback` changed to True toast once `Using System Default because <saved label> is unavailable`; never persist the fallback. In `toggle()`, keep the exception object and log it with `exc_info` so the PortAudio message lands in app.log. Use `getattr(..., None)` when reading `last_resolution` so the test fakes keep working.
5. `tray.py`: the Microphone radio checks the saved identity against live rows (the hint may be stale). Add `set_microphone_label(label)`; the tooltip becomes `Speech - <status> - <label>` truncated to 120 characters. Controller sets it at startup and on selection change; do not enumerate devices inside `set_status`.
6. Tests: stale hint resolves by name; missing device falls back to System Default and the fallback is not saved; toast fires once per change; `extra_settings` only for WASAPI rows; WDM-KS rows hidden; wake listener restarts on selection change; identity adoption at startup; existing int-keyed tests updated, not deleted.
7. `docs/configuration.md`: document the three keys and the fallback behaviour, one sentence per line, no em dashes.

## Verify before reporting
Run: `env -u SSLKEYLOGFILE .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
Run: `env -u SSLKEYLOGFILE .venv/Scripts/python.exe -c "from winwhisper.audio_inputs import list_audio_input_devices, resolve_input_device; d=list_audio_input_devices(); print([(x.index,x.name[:28],x.host_api) for x in d]); print(resolve_input_device('Desktop Microphone (RØDE PodMic', 'MME', 3, d))"`
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
