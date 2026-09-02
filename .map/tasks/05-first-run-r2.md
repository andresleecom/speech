# Task 05 follow-up: Start at login only for the installed app

You are the MAP executor (Grok CLI). Obey HARD RULES. No git. End with ## REPORT.

## Goal
The tray item "Start at login" must only write the HKCU Run value when Speech runs as the frozen installed executable. From a source checkout `sys.executable` is a bare python.exe, so enabling it today would register an interpreter to launch at sign-in.

## Context - read these first
- `src/winwhisper/tray.py`: `_on_toggle_startup` calls `startup_module.enable(sys.executable)`; the item is `visible=sys.platform == "win32"`.
- `src/winwhisper/startup.py`: `is_enabled`, `enable(exe_path)`, `disable`.
- `src/winwhisper/updater.py` (~line 190) shows the existing `getattr(sys, "frozen", False)` guard pattern.
- `tests/test_tray.py` and `tests/test_startup.py`.

## Scope - you may edit
- `src/winwhisper/tray.py`, `src/winwhisper/startup.py`, `tests/test_tray.py`, `tests/test_startup.py`

## Out of scope - do not touch
- Everything else.

## Steps
1. `startup.py`: add `installed_executable() -> str | None` returning `sys.executable` only when `getattr(sys, "frozen", False)` is true on win32, else `None`.
2. `tray.py` `_on_toggle_startup`: when not enabled and `installed_executable()` is `None`, notify `Start at login is available in the installed Speech app.` and return without writing; disabling stays allowed. Keep the item visible on win32.
3. Tests: enabling from a non-frozen process writes nothing and notifies; enabling from a fake frozen process writes the quoted path.

## Verify before reporting
Run: `env -u SSLKEYLOGFILE .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_tray.py tests/test_startup.py`
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
