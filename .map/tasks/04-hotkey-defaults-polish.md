# Task 04: Hotkey editor polish and conflict-free defaults

You are the MAP executor (Grok CLI). Obey HARD RULES. No git. End with ## REPORT.

## Goal
New profiles no longer ship hotkeys that common apps consume (Ctrl+Shift+E/S in VS Code, browsers, Word; Control+Option+Space is macOS's input-source switcher), bare F10/F11 stop being suggested, Linux stops accepting triggers pynput cannot report, and the Tk hotkey and language dialogs get a consistent title, an app icon instead of the Tk feather, an aligned grid, and neutral status text. Existing saved profiles are never changed.

## Context - read these first
- `src/winwhisper/hotkey_actions.py`: `_TOGGLE_SUGGESTIONS` (has `<f10>`, `<f11>`), `HOTKEY_ACTIONS` with `default_combo` values, `DEFAULT_HOTKEYS`.
- `src/winwhisper/hotkey_settings.py`: `normalize_hotkey_input` (darwin-only pageup/pagedown remap ~line 143), `normalize_hotkey_profile`, `_validate_platform_trigger` (no-op off win32/darwin), `display_hotkey`.
- `src/winwhisper/hotkey_settings_window.py`: `_run_tk_dialog` (title with an em dash at ~line 179, `columnspan=2` rows, `_ACCENT` used for the informational "Press a mouse button now" hint at ~line 163).
- `src/winwhisper/language_settings_window.py`: `_run_tk_dialog` (title with a hyphen, no icon).
- `src/winwhisper/tray.py`: `_make_icon_image` draws the status circle with PIL; `src/winwhisper/branding.py` holds `APP_NAME`.
- `src/winwhisper/config.py`: `Settings.hotkeys` defaults from `DEFAULT_HOTKEYS` only when the key is absent from the file.
- Tests: `tests/test_hotkey_settings.py`, `tests/test_hotkey_settings_window.py`, `tests/test_language_settings_window.py`, `tests/test_hotkeys.py`, `tests/test_config.py`.

## Scope - you may edit
- `src/winwhisper/hotkey_actions.py`, `hotkey_settings.py`, `hotkey_settings_window.py`, `language_settings_window.py`, `branding.py`, `tray.py` (only to reuse the icon helper), `config.py` (only if a migration guard is needed)
- `tests/test_hotkey_settings.py`, `test_hotkey_settings_window.py`, `test_language_settings_window.py`, `test_hotkeys.py`, `test_config.py`, `test_tray.py`
- `README.md` (hotkey table only), `docs/configuration.md` (Hotkeys section only)

## Out of scope - do not touch
- `hotkeys.py` engine behaviour, `main.py`, everything else.

## Steps
1. `hotkey_actions.py`: drop `<f10>` and `<f11>` from `_TOGGLE_SUGGESTIONS`; add `macos_default_combo` to `HotkeyAction` with `<ctrl>+<shift>+<space>` for the toggle and make `DEFAULT_HOTKEYS` resolve per platform through a `default_hotkeys(platform)` helper (Windows/Linux keep `<ctrl>+<alt>+<space>`); set the two language defaults to `""` (disabled) for new profiles; keep the suggestions so users can enable them from the dialog.
2. `hotkey_settings.py`: apply the pageup/pagedown to page_up/page_down remap on linux as well as darwin; give `_validate_platform_trigger` a linux branch that accepts single characters, `f1` to `f20`, and an allowlist of pynput key names (space, enter, tab, esc, backspace, delete, insert, home, end, page_up, page_down, arrows, numpad_* ) and rejects anything else with a clear message. Make sure `normalize_hotkey_profile` fills only absent keys with defaults, never overwrites saved values.
3. `branding.py`: add `app_icon_image(size=64)` returning the PIL circle the tray draws for Idle (move the drawing there and have `tray._make_icon_image` reuse it). Both Tk dialogs call `root.iconphoto(True, ImageTk.PhotoImage(...))` inside `try/except` and use the hyphen title `Speech Settings - Hotkeys` / `Speech Settings - Languages`.
4. `hotkey_settings_window.py`: `columnspan=3` on the subtitle, status, and button rows so they span the Record column; informational status text uses a neutral grey, errors keep `_ACCENT`.
5. Docs: README hotkey table shows Favorite 1 and 2 as Disabled by default and the macOS toggle as `Control+Shift+Space`; `docs/configuration.md` says the same and notes that existing profiles keep their shortcuts. One sentence per line, no em dashes.
6. Tests: defaults per platform; language defaults disabled; a saved profile with the old defaults is untouched after load and normalize; F10/F11 absent from suggestions; linux rejects `page_up` misspellings and accepts `<ctrl>+<alt>+page_up`; the dialogs set an icon and the hyphen title (extend the existing fake Tk in the window tests).

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
