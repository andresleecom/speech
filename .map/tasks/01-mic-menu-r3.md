# Task 01 follow-up 2: refresh the device table only when devices change

You are the MAP executor. Obey HARD RULES. No git. End with ## REPORT.

## Goal
`TrayApp._microphone_menu_items` calls `refresh_audio_device_table()` on every menu rebuild, and pystray rebuilds the menu on every status change, so a 36 ms PortAudio re-init runs three times per take for nothing. Move the refresh into the device poll: when the input-device signature changes, refresh the table (it is already guarded against open streams) and then rebuild the menu; the submenu builder only lists and groups.

## Context - read these first
- `src/winwhisper/tray.py`: `_microphone_menu_items`, `_poll_input_devices`, `_start_input_device_polling`.
- `src/winwhisper/audio_inputs.py`: `refresh_audio_device_table` (returns None when a stream is open or on macOS).
- `tests/test_tray.py`: the tests added for the poll and for the submenu.

## Scope - you may edit
- `src/winwhisper/tray.py`, `tests/test_tray.py`

## Out of scope - do not touch
- Everything else.

## Steps
1. Remove the `refresh_audio_device_table()` call from `_microphone_menu_items`.
2. In `_poll_input_devices`, when the signature changed, call `refresh_audio_device_table()` before `refresh_menu()`; if it returns None because a stream is open, still refresh the menu and keep polling (the next change or the recorder's own refresh will catch up).
3. Tests: the submenu builder no longer refreshes; the poll refreshes exactly once per change and never when unchanged.

## Verify before reporting
Run: `env -u SSLKEYLOGFILE .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_tray.py tests/test_audio_inputs.py`
Paste the output in your REPORT under PROOF.

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
