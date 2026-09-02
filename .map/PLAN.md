# MAP: Speech release 1 - the reliability floor

**Goal:** A trial user on Windows never hits the microphone-index failure, sees an honest message when a take captures nothing, receives every startup notification, and learns the hotkey and the model download on first launch.
**Base:** main @ e9a4dae · **Branch:** map/release-1-reliability · **Tier:** L (recon done by the 2026-09-01 two-pass review; prism skipped)
**Non-goals:** everything in the review's NEXT and LATER tiers: icon, code signing, push-to-talk, chord capture, formatter changes, hands-free tuning, orb changes, updater, settings window, model picker, macOS/Linux start-at-login, Wayland, rename.

## Decisions
- D01 Orchestrator = fable-5 (Claude Code). Never types product code.
- D02 Executor primary = grok-4.5 CLI; fallback codex gpt-5.6-sol, then Opus 4.8 subagent.
- D03 Scope = the five release-1 items from the review, one task each, sequential (they share main.py, recorder.py, tray.py, config.py).
- D04 One branch, one commit per verified task, one PR at the end; Andres merges. Merging to main auto-publishes v0.1.19.<run>, so pyproject bumps 0.1.18 -> 0.1.19 in the last task.
- D05 Windows-first. macOS and Linux must keep passing tests and must not regress, but get no new features here.
- D06 Microphone identity = two new settings fields `audio_input_device_name: str | None` and `audio_input_device_host_api: str | None` next to the existing `audio_input_device: int | None` (kept as a hint and for old files). On macOS `host_api` stores the AVFoundation uniqueID. Migration resolves an old int against the live table at load and never raises.
- D07 Resolution order at every stream open: exact name + host API; then any input row with the same name that passes `sd.check_input_settings(device, samplerate=16000, channels=1, dtype="int16")`; then System Default. A fallback is used, toasted once per change, and never persisted.
- D08 `extra_settings=sd.WasapiSettings(auto_convert=True)` only when the host API name is `Windows WASAPI`. WDM-KS rows are dropped from the device listing. No in-process resampling.
- D09 Silent-take rules: zero frames skips Whisper and toasts "Nothing was captured from <mic>"; an empty transcription with peak == 0.0 toasts "<mic> delivered silence"; otherwise the existing "No speech detected". No RMS gate before inference, no hallucination blocklist.
- D10 Tray notifications are queued while the icon does not exist and drained in pystray's `setup` callback after `icon.visible = True`.
- D11 Settings recovery: on a pydantic ValidationError drop only the offending top-level keys (bounded retry), keep the `.corrupt` backup, and hand a notice string to the controller for delivery through the queue. JSON syntax errors keep today's behaviour plus the notice.
- D12 First run = hotkey shown in the tray toggle label and the tooltip; one toast when no settings file existed at load; a "Downloading speech model <size> (<MB>)" toast from a Hugging Face cache probe before warmup; offline load failures get a specific message; lenient `model_size` validator; Windows "Start at login" as an Inno [Tasks] entry plus a tray check item writing HKCU Run.
- D13 The Intel macOS build becomes non-blocking for publish (`continue-on-error` on the job, publish tolerates missing intel assets) so a retired runner cannot stop releases.
- D14 Verification of the microphone task: orchestrator drives a stale-index settings file against the live device table and opens a real stream on the RØDE; Andres does the 3+ real spoken takes before merge.
- D15 A saved index hint with no saved name is legacy state, not a System Default choice: if the hint matches a live input row use it; if it matches nothing resolve to System Default with `fallback=True` so the toast fires. Only `name is None and index_hint is None` means the user chose System Default. Toasts stay short: PortAudio text and the resolved device go into `RecorderError.details` and the log, not the balloon.

## Constraints
- Never set argtypes on `ctypes.windll.*`; modules use private `ctypes.WinDLL(...)` handles (regression tests exist).
- Keep `load_settings()` and public controller method signatures backward compatible; add, do not rename.
- No new dependencies. `huggingface_hub` is importable transitively; guard the import.
- Tests must not touch the real `%APPDATA%\Speech`; task 01 makes that structural.
- Markdown edits: one sentence per line. No em dashes anywhere.
- Run Python as `env -u SSLKEYLOGFILE .venv/Scripts/python.exe` (Norton injects SSLKEYLOGFILE).

## Verify commands
- tests: `env -u SSLKEYLOGFILE .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
- import smoke: `env -u SSLKEYLOGFILE .venv/Scripts/python.exe -c "import winwhisper.main, winwhisper.tray, winwhisper.recorder, winwhisper.config"`
- flow check (orchestrator): launch from source, confirm the startup log line, tray label, and device resolution against a settings file with `audio_input_device: 3`.

## Tasks
| # | Task | Scope (files/areas) | Bar | Status |
|---|------|---------------------|-----|--------|
| 01 | Test isolation, deflake, CI timeouts, version in startup log, non-blocking intel dmg | tests/conftest.py, tests/test_wake_word.py, .github/workflows/ci.yml, .github/workflows/release.yml, src/winwhisper/main.py (startup line), src/winwhisper/diagnostics.py, src/winwhisper/logger.py | build+tests | done |
| 02 | Stable microphone identity with fallback, WASAPI auto-convert, WDM-KS hidden, wake listener restart, real PortAudio error in log | src/winwhisper/audio_inputs.py, config.py, recorder.py, wake_word_source.py, main.py, tray.py, tests/test_audio_inputs.py, test_config.py, test_recorder.py, test_overlay_flow.py, test_tray.py, test_wake_word.py, docs/configuration.md | build+tests+flow | done |
| 03 | Silent and dead take diagnosis with per-take stats and timing line | src/winwhisper/recorder.py, main.py, tests/test_recorder.py, test_overlay_flow.py | build+tests+flow | done |
| 04 | Notification queue, Open Log Folder, version item, drop-only-bad-keys settings recovery | src/winwhisper/tray.py, main.py, config.py, tests/test_tray.py, test_config.py, test_main.py, test_overlay_flow.py | build+tests+flow | done |
| 05 | First run: hotkey in tray, model download toast, offline message, lenient model_size, Windows start at login, version bump | src/winwhisper/main.py, tray.py, config.py, transcriber.py, hotkey_actions.py, installer/Speech.iss, pyproject.toml, README.md, docs/configuration.md, tests | build+tests+flow | pending |

Bar legend: build = diff review + import smoke · +tests = also the full pytest run · +flow = also drive the affected flow from source.

Status values: `pending` · `done` · `blocked` · `takeover`.
