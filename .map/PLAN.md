# MAP: Speech release 2 - ergonomics a daily user compares on

**Goal:** The microphone menu shows one entry per physical microphone, text never pastes into a window that replaced the target, the hotkey can be held to record, chords are bound by pressing them, and the daily text defects (leading-digit capitalization, glued takes, stock hallucinations) are gone.
**Base:** map/hotfix-device-refresh @ c5bdd63 (main plus the unmerged 0.1.20 hotfix, PR #57) · **Branch:** map/release-2-ergonomics · **Tier:** L (scope locked by the 2026-09-01 review verdicts)
**Non-goals:** icon, code signing, orb changes, updater, settings window, model picker, hands-free tuning, macOS-only editors, rename.

## Decisions
- D01 Orchestrator = fable-5; executor primary = grok-4.5; fallback codex gpt-5.6-sol, then Opus 4.8.
- D02 Base on the hotfix branch because PR #57 is still open; rebase onto main once it merges, before opening the PR.
- D03 Sequential tasks, one commit each, version bump to 0.1.21 in the last task.
- D04 Microphone menu: one entry per physical microphone, keyed by name; the entry's selection stores the name plus the preferred host API row (the first row that passes the 16 kHz capture check, MME first on Windows); the submenu is rebuilt each time the menu opens and refreshes the PortAudio table first when no stream is open; a saved microphone that is missing shows one disabled "unavailable" entry.
- D05 Windows paste guard: after restoring focus, paste only if `GetForegroundWindow()` equals the captured window or belongs to the same process; otherwise keep the text on the clipboard and notify. Linux keeps its existing abort; macOS unchanged (no window is captured there).
- D06 Push-to-talk: recording starts on press exactly as today; if the chord is still held 500 ms later it becomes push-to-talk and a distinct `toggle_release` action stops on key-up; Windows polls `GetAsyncKeyState` via a private `ctypes.WinDLL` (no low-level keyboard hook); holds shorter than the minimum take stay toggles; wait up to 1 s for modifiers to clear before pasting; macOS, Linux, and mouse bindings stay toggle-only this release.
- D07 Hotkey editor: Tk `<KeyPress>` chord capture on Windows/Linux with the live hotkey manager stopped around the dialog; defaults change to combos common apps do not consume and language hotkeys ship disabled for new profiles (existing profiles untouched); no bare F10/F11 suggestions; OEM and non-ASCII keys bind through `VkKeyScanExW`; Linux validates triggers against what pynput can report; hyphen titles, app-icon placeholder, grid fix.
- D08 Text processing: capitalize only a leading letter (or one after opening punctuation); append one trailing space when cleaned text ends in sentence punctuation (skipped in cleanup mode `none`); opt-in newline commands in English and Spanish only; a normalized whole-text blocklist of stock Whisper phrases treated as "No speech detected"; no period/comma tables, no filler removal, no per-favorite profiles.
- D09 Anything touching device selection is validated with a Bluetooth headset toggle before merge (lesson from 0.1.19.41).
- D10 Task 01 executor = codex gpt-5.6-sol (executor-switch: grok-4.5 API returned 500 "service temporarily unavailable" on two consecutive dispatches).
- D11 pystray caches the Win32 popup menu and only rebuilds it on `update_menu`, so "rebuilt on open" is implemented as a 2 s device-signature poll (private `ctypes.WinDLL("winmm")`, `waveInGetNumDevs` plus `waveInGetDevCapsW`, about 0.4 ms) that calls `refresh_menu()` when the set of input devices changes; the PortAudio mapper pseudo-devices are hidden from the menu.
- D12 Task 04 executor = Opus subagent (executor-switch: grok-4.5 API 500 and codex backend 404 on the same dispatch); packets, HARD RULES and the pass gate are unchanged.

## Constraints
- Never set argtypes on `ctypes.windll.*`; private `ctypes.WinDLL` handles only. No new dependencies. Markdown: one sentence per line, no em dashes. Run Python as `env -u SSLKEYLOGFILE .venv/Scripts/python.exe`.

## Verify commands
- tests: `env -u SSLKEYLOGFILE .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
- flow (orchestrator): drive each affected path from source against real devices or the real hotkey engine as noted per task.

## Tasks
| # | Task | Scope (files/areas) | Bar | Status |
|---|------|---------------------|-----|--------|
| 01 | Microphone menu: one entry per physical mic, rebuilt on open, refresh-aware | src/winwhisper/audio_inputs.py, tray.py, main.py, tests/test_audio_inputs.py, test_tray.py, test_overlay_flow.py, docs/configuration.md | build+tests+flow | done |
| 02 | Windows: do not paste when the target window changed | src/winwhisper/focus.py, main.py, tests/test_focus.py, test_overlay_flow.py | build+tests+flow | done |
| 03 | Push-to-talk on Windows keyboard hotkeys | src/winwhisper/hotkeys.py, hotkey_actions.py, main.py, tests/test_hotkeys.py, test_overlay_flow.py, docs | build+tests+flow | done |
| 04 | Hotkey editor polish and conflict-free defaults | src/winwhisper/hotkey_actions.py, hotkey_settings.py, hotkey_settings_window.py, config.py, tests, docs | build+tests+flow | done |
| 05 | Hotkey editor chord capture and OEM keys | src/winwhisper/hotkey_settings_window.py, hotkey_settings.py, hotkeys.py, main.py, tests | build+tests+flow | done |
| 06 | Text processing fixes and version 0.1.21 | src/winwhisper/formatter.py, main.py, config.py, tray.py, pyproject.toml, tests, docs | build+tests+flow | done |

Bar legend: build = diff review + import smoke · +tests = full pytest · +flow = drive the affected path from source.
