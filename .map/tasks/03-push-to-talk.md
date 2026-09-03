# Task 03: Push-to-talk on Windows keyboard hotkeys (tap toggles, hold records while held)

You are the MAP executor (Grok CLI). Obey HARD RULES. No git. End with ## REPORT.

## Goal
A tap of the dictation hotkey keeps working as a toggle. Holding it for 500 ms or longer turns the take into push-to-talk: recording started on the press as today, and releasing the chord stops and transcribes. Windows keyboard bindings only this release; mouse bindings, macOS and Linux stay toggle-only.

## Context - read these first
- `src/winwhisper/hotkeys.py`: `HotkeyManager` (Win32 `RegisterHotKey` with `_MOD_NOREPEAT`, so Windows posts exactly one `WM_HOTKEY` per press and never a release); the message loop around line 551-610 and `_dispatch(action)` (~line 611) which spawns a thread per press; `windows_modifier_state()` (~line 187) shows the private `ctypes.WinDLL("user32")` plus `GetAsyncKeyState` pattern to reuse; `_bindings` entries carry `(hotkey_id, fs_modifiers, vk, action, combo)`. The class docstring records that a low-level keyboard hook was torn down by Windows once the overlay opened: do not add a hook.
- `src/winwhisper/main.py`: `on_hotkey(action)` (~line 342) routes `toggle`; `toggle()` starts or stops; `_request_stop` / `_begin_stop_locked` stop a take; `_stop_and_process` pastes via `insert_text`.
- `src/winwhisper/hotkey_actions.py`: `HOTKEY_ACTIONS` with `dispatch_action="toggle"`.
- `tests/test_hotkeys.py` (fake Win32 message loop and dispatch callbacks), `tests/test_overlay_flow.py` (controller harness with `ImmediateThread`).
- Facts: the existing `_ACTION_DEBOUNCE_SECONDS` guard in the mouse backend would swallow a quick re-fired `toggle`, so the release must be its own action name. Ctrl+Alt+V is AltGr+V on Andres's Spanish layout, so modifiers must be up before the paste chord.

## Scope - you may edit
- `src/winwhisper/hotkeys.py`, `src/winwhisper/hotkey_actions.py`, `src/winwhisper/main.py`
- `tests/test_hotkeys.py`, `tests/test_overlay_flow.py`
- `README.md` ("How it works" section only), `docs/configuration.md` (Hotkeys section only)

## Out of scope - do not touch
- Mouse backend behaviour, `_PynputHotkeyBackend` (macOS/Linux), settings windows, everything else.

## Steps
1. `hotkeys.py` Win32 backend: when `WM_HOTKEY` arrives for a binding whose action is `toggle`, after dispatching `toggle` start one poll thread (15 ms period, private `ctypes.WinDLL("user32")`, `GetAsyncKeyState` on the trigger vk) that watches the trigger key; if it is still down 500 ms after the press, mark the take as push-to-talk; when the key goes up after that mark, dispatch `toggle_release`; if it goes up before 500 ms, dispatch nothing. Only one poll at a time; a new press while one is running replaces it; `stop()` ends the poll. Add `PUSH_TO_TALK_HOLD_SECONDS = 0.5`.
2. `hotkey_actions.py`: add the `toggle_release` dispatch action constant next to `toggle` (no new settings key, no new UI).
3. `main.py`: `on_hotkey("toggle_release")` stops the take through the same path as a second press only when a recording is in progress and not processing; log it as `push_to_talk_release`. Before `insert_text` in `_stop_and_process`, on Windows wait up to 1 s (30 ms steps) for `windows_modifier_state()` to be empty so the paste chord is not typed with Ctrl or Alt still held.
4. Docs: README "How it works" step 3 gains "or hold the hotkey and release it to stop"; `docs/configuration.md` Hotkeys section gets one sentence each for tap, hold, and the Windows-keyboard-only limit. One sentence per line, no em dashes.
5. Tests: `test_hotkeys.py` with a fake `GetAsyncKeyState` and a controllable clock: held past 500 ms then released dispatches `toggle` then `toggle_release`; released at 200 ms dispatches only `toggle`; `stop()` ends the poll; a second press replaces the poll. `test_overlay_flow.py`: `toggle_release` while recording stops and pastes; while idle it is ignored; the modifier wait is skipped when modifiers are already up and bounded when they never clear (patch `windows_modifier_state`).

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
