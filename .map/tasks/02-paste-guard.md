# Task 02: Windows: do not paste when the target window is no longer in front

You are the MAP executor (Grok CLI). Obey HARD RULES. No git. End with ## REPORT.

## Goal
On Windows, when the window captured at the start of a take cannot be brought back to the front, Speech currently sends Ctrl+V into whatever is in front (16 of 938 pastes in the log). After this task it pastes only when the captured window, or another window of the same process, is actually in the foreground; otherwise it leaves the text on the clipboard and says so. Linux keeps its existing abort branch; macOS is unchanged because no window is captured there.

## Context - read these first
- `src/winwhisper/focus.py`: `get_foreground_window`, `restore_foreground_window` (returns False when `IsWindow` fails or `SetForegroundWindow` is refused, which also happens when the target is already in front), `GetWindowThreadProcessId` usage near line 100. It uses the shared `ctypes.windll.user32` without setting argtypes; keep it that way or use a private `ctypes.WinDLL("user32")`.
- `src/winwhisper/main.py`: `_stop_and_process` around the `restored_target = self._restore_paste_target()` call (~line 1235) and the Linux-only abort branch right after it; `_restore_paste_target` (~line 1345); `insert_text` call.
- `src/winwhisper/inserter.py`: `insert_text(text, shortcut=...)` copies then sends the chord. Add a copy-only helper if none exists.
- `tests/test_overlay_flow.py`: `test_failed_windows_focus_restore_still_attempts_paste` (~line 1212) locks in the current behaviour with `restore_foreground_window` patched to False; the harness `make_controller` and the fake window handle constant (777) used by the focus fakes.
- `tests/test_focus.py` for the focus test patterns.

## Scope - you may edit
- `src/winwhisper/focus.py`, `src/winwhisper/main.py`, `src/winwhisper/inserter.py`
- `tests/test_focus.py`, `tests/test_overlay_flow.py`, `tests/test_inserter.py`

## Out of scope - do not touch
- Everything else.

## Steps
1. `focus.py`: add `foreground_matches(hwnd) -> bool | None`: `None` when not on Windows or `hwnd` is None; otherwise poll up to 300 ms in 30 ms steps until `GetForegroundWindow()` equals `hwnd` or belongs to the same process id (`GetWindowThreadProcessId`), returning True on match and False on timeout. Never set argtypes on `ctypes.windll.*`.
2. `main.py`: after `_restore_paste_target()`, on Windows call `foreground_matches(self._paste_target_window)`; when it returns False, copy the cleaned text to the clipboard with the copy-only helper, log `Target window changed; text left on the clipboard.`, notify `Target window changed. The text is on the clipboard; press Ctrl+V to paste it.`, and return without sending the chord. When it returns True or None, proceed exactly as today. Keep the Linux branch unchanged.
3. Tests: rewrite `test_failed_windows_focus_restore_still_attempts_paste` so the restore returns False but the foreground still matches (the refused-but-in-front case) and the paste still happens; add a test where the foreground differs (no paste, text copied, the toast above); add a `foreground_matches` unit test with fakes for the Win32 calls; a non-Windows test proving the guard is skipped.

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
