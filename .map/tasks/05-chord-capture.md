# Task 05: Bind keyboard chords by pressing them; bind OEM keys on Spanish layouts

You are the MAP executor (Grok CLI). Obey HARD RULES. No git. End with ## REPORT.

## Goal
In the Windows and Linux hotkey dialog, pressing Record and then pressing a keyboard chord binds it (today Record captures mouse buttons only and keyboard shortcuts must be typed as text). Keys that the name table cannot express, such as `<`, `º` or `ñ` on an es-ES layout, bind through the layout, and a Ctrl+Alt+printable chord that AltGr would type is rejected with a message. macOS keeps its current editor.

## Context - read these first
- `src/winwhisper/hotkey_settings_window.py`: `_make_record_command` (creates a `MouseCapture`), the Record buttons in `_run_tk_dialog`, `_choice_labels`, the save path.
- `src/winwhisper/hotkey_settings.py`: `normalize_hotkey_input`, `display_hotkey`, the modifier and trigger name tables.
- `src/winwhisper/hotkeys.py`: `trigger_to_vk` (~line 158, name table), `windows_modifier_state()` (~line 187, private `ctypes.WinDLL("user32")` pattern). `RegisterHotKey` consumes bound chords before Tk sees them, so the live manager must be stopped while the dialog captures.
- `src/winwhisper/main.py`: `open_hotkey_settings` (~line 851) and the save handler that stops and restarts `self.hotkeys` with rollback (~line 780-830); `HotkeySettingsWindow.show(hotkeys, on_save, language_favorites)`.
- Tk facts: on Windows `event.keycode` is the virtual-key code and `event.state` carries Control (0x4), Shift (0x1) and Alt (0x20000) bits; the Win key is not in `state`, so read it with `windows_modifier_state()`. On Linux `event.keysym` gives names like `Prior`, `KP_Add`, `space`, `a`.
- Win32 facts: `VkKeyScanExW(ch, layout)` maps a character to a VK on the current layout; `ToUnicodeEx` with the shift state for Ctrl+Alt (AltGr) tells whether a VK produces a character under AltGr. Use a private `ctypes.WinDLL("user32")`; never set argtypes on `ctypes.windll`.
- Tests: `tests/test_hotkey_settings.py`, `tests/test_hotkey_settings_window.py` (fake Tk), `tests/test_hotkeys.py`, `tests/test_overlay_flow.py`.

## Scope - you may edit
- `src/winwhisper/hotkey_settings_window.py`, `hotkey_settings.py`, `hotkeys.py`, `main.py`
- `tests/test_hotkey_settings.py`, `test_hotkey_settings_window.py`, `test_hotkeys.py`, `test_overlay_flow.py`
- `docs/configuration.md` (Hotkeys section only)

## Out of scope - do not touch
- The macOS NSAlert editor, mouse capture internals, everything else.

## Steps
1. `hotkey_settings.py`: add `combo_from_key_event(*, keycode, keysym, state, platform, extra_modifiers=()) -> str | None` that turns a Tk key event into the serialized combo (`<ctrl>+<alt>+<space>`, `<ctrl>+<shift>+<f8>`, `<ctrl>+<alt>+<`), returning None for a bare modifier press; printable keys keep the existing "modifier required" rule.
2. `hotkey_settings_window.py`: while Record is active, bind `<KeyPress>` on the root so the first non-modifier key press fills the combo box through `combo_from_key_event` and ends capture; mouse capture keeps working in parallel and whichever arrives first wins; Escape cancels. `HotkeySettingsWindow.show` gains optional `on_capture_begin` and `on_capture_end` callbacks invoked around the whole dialog lifetime (open and close, including save and error paths, in `finally`).
3. `main.py`: pass callbacks that stop the live hotkey manager when the dialog opens and start it again when the dialog closes, reusing the existing restart path; log both.
4. `hotkeys.py`: extend `trigger_to_vk` so a single character not in the name table maps through `VkKeyScanExW` on the current layout via a private `ctypes.WinDLL("user32")`; add `altgr_produces_character(vk) -> str | None` using `ToUnicodeEx` with the Ctrl+Alt shift state; `hotkey_settings.normalize_hotkey_input` rejects a Ctrl+Alt+printable chord on Windows when that helper returns a character, with the message `Ctrl + Alt + <key> types "<char>" on your keyboard layout; choose another combination.`
5. `docs/configuration.md`: replace the "type one such as Ctrl + Alt + Space" guidance with "press Record and then the keys". One sentence per line, no em dashes.
6. Tests: `combo_from_key_event` for space, F8, a letter, `<` (keycode via a fake scan), a bare Ctrl press (None), Linux `Prior` -> `page_up`; the fake Tk dialog receives a key event during Record and fills the box; the callbacks fire on open and close including when save raises; `trigger_to_vk("<")` through a fake `VkKeyScanExW`; the AltGr rejection message.

## Verify before reporting
Run: `env -u SSLKEYLOGFILE .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
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
