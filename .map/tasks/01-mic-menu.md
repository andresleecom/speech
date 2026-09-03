# Task 01: Microphone menu with one entry per physical microphone, rebuilt on open

You are the MAP executor (Grok CLI). Obey HARD RULES. No git. End with ## REPORT.

## Goal
The tray Microphone submenu lists each physical microphone once (today it lists 15 rows for 5 devices, one per host API, with raw indices and MME-truncated names), rebuilds itself every time the menu opens so a headset connected after launch appears, and selecting an entry stores a stable identity instead of an index.

## Context - read these first
- `src/winwhisper/audio_inputs.py`: `AudioInputDevice(index, name, input_channels, host_api)`, `list_audio_input_devices`, `resolve_input_device`, `refresh_audio_device_table` (guarded, ~40 ms), `_device_supports_capture`.
- `src/winwhisper/tray.py`: `_make_microphone_menu`, `_selection_action`, `_select_audio_input_device`, `_device_checked`, `_saved_microphone_missing`, `_unavailable_microphone_label`, `refresh_menu`.
- `src/winwhisper/main.py`: `set_audio_input_device(value)` (index in, records name and host API from the live table, restarts the wake listener, saves).
- pystray: `Menu(callable)` with a single callable argument calls it on every `Menu.items` access, so a submenu built that way re-enumerates when the menu opens; `MenuItem.text` and `checked` accept callables.
- Live facts: MME names are truncated to 31 characters (`Desktop Microphone (RØDE PodMic`), WASAPI and DirectSound carry the full name (`Desktop Microphone (RØDE PodMic USB)`); the same mic appears under MME, DirectSound and WASAPI; WDM-KS rows are already hidden.
- Tests: `tests/test_audio_inputs.py`, `tests/test_tray.py` (FakeMenu/FakeItem pattern), `tests/test_overlay_flow.py`.

## Scope - you may edit
- `src/winwhisper/audio_inputs.py`, `tray.py`, `main.py`
- `tests/test_audio_inputs.py`, `tests/test_tray.py`, `tests/test_overlay_flow.py`
- `docs/configuration.md` (Microphone section only)

## Out of scope - do not touch
- `recorder*.py`, `wake_word*.py`, `config.py`, everything else.

## Steps
1. `audio_inputs.py`: add `PhysicalInputDevice(label: str, rows: tuple[AudioInputDevice, ...], preferred: AudioInputDevice)` and `group_physical_input_devices(devices) -> tuple[PhysicalInputDevice, ...]`. Group rows whose names are equal or where one name is a 31-character prefix of the other (the MME truncation); `label` is the longest name in the group; `preferred` is the first row in host-API order MME, Windows WASAPI, Windows DirectSound, then anything else, that passes `_device_supports_capture`; on macOS every row is its own group. Keep the group order stable (first appearance).
2. `main.py`: add `set_audio_input_selection(name: str | None, host_api: str | None)` that stores the identity directly (index hint = the live index if found, else None), restarts the wake listener like `set_audio_input_device` does, saves, updates the tooltip label with the group label, and refreshes the menu; keep `set_audio_input_device(index)` working by delegating to it.
3. `tray.py`: build the Microphone submenu as `menu_cls(self._microphone_menu_items)` where the callable calls `refresh_audio_device_table()`, lists devices, groups them, and returns: the System Default radio item; one radio item per physical microphone labelled with the group label (no index), checked when any row of the group matches the saved name and host API (or the saved name with no exact host-API match); one disabled `<saved name> (unavailable)` item when the saved identity matches no group; `No microphone available` when the list is empty; then `Test Microphone`. Selecting a group calls `controller.set_audio_input_selection(preferred.name, preferred.host_api)`. Keep `refresh_menu()` working. If FakeMenu in the tests does not accept a callable, extend the fake, not the production code.
4. `docs/configuration.md`: say the menu shows one entry per microphone and re-scans when opened. One sentence per line, no em dashes.
5. Tests: grouping of MME-truncated, DirectSound and WASAPI rows into one entry with the full label and the MME row preferred; a row that fails the capture check is not preferred; a headset row added to the fake device table after the first build appears on the next build; checked state follows the saved identity; the unavailable entry; selection stores name and host API and the index hint; existing tests updated, not deleted.

## Verify before reporting
Run: `env -u SSLKEYLOGFILE .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
Run: `env -u SSLKEYLOGFILE .venv/Scripts/python.exe -c "from winwhisper.audio_inputs import list_audio_input_devices, group_physical_input_devices; [print(g.label, '->', g.preferred.index, g.preferred.host_api, [r.host_api for r in g.rows]) for g in group_physical_input_devices(list_audio_input_devices())]"`
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
