# Task 01 follow-up: hide mapper pseudo-devices; rebuild the menu when devices change

You are the MAP executor. Obey HARD RULES. No git. End with ## REPORT.

## Goal
Two corrections to the task 01 work already in the working tree (do not redo it). First, the PortAudio pseudo-devices `Microsoft Sound Mapper - Input` (MME) and `Primary Sound Capture Driver` (DirectSound) are aliases of System Default and must not appear as microphones. Second, pystray's Windows backend caches the popup menu and only rebuilds it when `update_menu()` is called, so the submenu callable alone does not re-scan when the user opens the menu; the tray must notice device changes and refresh the menu itself.

## Context - read these first
- `src/winwhisper/audio_inputs.py`: `group_physical_input_devices`, `_SKIPPED_HOST_APIS`, `_sounddevice_host_api_name`.
- `src/winwhisper/tray.py`: `_microphone_menu_items`, `refresh_menu`, `run()` (creates the icon and calls `icon.run(setup=self._on_icon_ready)`), `stop()`, `_ui_lock`.
- `src/winwhisper/hotkeys.py` `windows_modifier_state()` (~line 187): the private `ctypes.WinDLL` pattern. Never set argtypes on `ctypes.windll.*`.
- Win32 facts: `winmm.waveInGetNumDevs()` and `waveInGetDevCapsW(i, &WAVEINCAPSW, sizeof)` list the current MME input devices in about 0.4 ms; `WAVEINCAPSW` is `wMid WORD, wPid WORD, vDriverVersion UINT, szPname WCHAR[32], dwFormats DWORD, wChannels WORD, wReserved1 WORD`.
- Tests: `tests/test_audio_inputs.py`, `tests/test_tray.py` (FakeIcon/FakeMenu).

## Scope - you may edit
- `src/winwhisper/audio_inputs.py`, `src/winwhisper/tray.py`
- `tests/test_audio_inputs.py`, `tests/test_tray.py`
- `docs/configuration.md` (the one sentence about re-scanning)

## Out of scope - do not touch
- Everything else.

## Steps
1. `audio_inputs.py`: add `_PSEUDO_INPUT_NAMES = frozenset({"Microsoft Sound Mapper - Input", "Primary Sound Capture Driver"})` and drop those rows in `group_physical_input_devices` (keep `list_audio_input_devices` unchanged so resolution by index still works). Add `input_device_signature() -> tuple[str, ...] | None`: on Windows return the tuple of `szPname` values from winmm through a private `ctypes.WinDLL("winmm")`; `None` on other platforms or on any error.
2. `tray.py`: after the icon is ready, start a daemon `threading.Timer` loop (2 s period) that computes `input_device_signature()`, and when it differs from the last value calls `refresh_menu()` and logs `Input devices changed; microphone menu refreshed.`; stop the loop in `stop()`; never run it when the signature is `None`. Keep the submenu callable as is.
3. `docs/configuration.md`: change the re-scan sentence to say the menu updates within a couple of seconds when a microphone is connected or disconnected, and always when it is rebuilt.
4. Tests: pseudo-devices are absent from the groups; `input_device_signature` with a fake winmm; the tray refreshes the menu when the signature changes and not when it is unchanged, and stops polling on `stop()` (use a fake timer or a controllable clock).

## Verify before reporting
Run: `env -u SSLKEYLOGFILE .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
Run: `env -u SSLKEYLOGFILE .venv/Scripts/python.exe -c "from winwhisper.audio_inputs import input_device_signature, list_audio_input_devices, group_physical_input_devices; print(input_device_signature()); print([g.label for g in group_physical_input_devices(list_audio_input_devices())])"`
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
