# MAP: hotfix - refresh the audio device table before every open

**Goal:** A Bluetooth headset connecting or disconnecting while Speech runs can no longer make a take record from the wrong microphone or from nothing.
**Base:** main (0.1.19 merged) · **Branch:** map/hotfix-device-refresh · **Tier:** S
**Non-goals:** tray menu dedupe, hands-free tuning beyond pausing the listener around hotkey takes.

## Decisions
- D01 Orchestrator = fable-5; executor primary = grok-4.5.
- D02 Root cause (from app.log 2026-09-02): PortAudio freezes the Windows waveIn device order at Pa_Initialize; Bluetooth connect/disconnect renumbers the real devices, so the saved name resolved against the stale table opened the Beats hands-free mic (3 s SCO stall, narrowband audio) or a dead slot (0 frames). A fresh process sees the RØDE in 37 ms.
- D03 Fix = `sd._terminate(); sd._initialize()` (measured 40 ms) before every sounddevice open, guarded by a process-wide open-stream count so it never runs while any stream is open. macOS (AVFoundation) needs nothing.
- D04 The wake-word listener is paused before a hotkey recording starts and resumed after the take, so the refresh can run and the two streams never overlap.
- D05 Version bumps to 0.1.20 so the auto-updater picks it up.

## Constraints
- Never set argtypes on `ctypes.windll.*`. No new dependencies. Run Python as `env -u SSLKEYLOGFILE .venv/Scripts/python.exe`.

## Verify commands
- tests: `env -u SSLKEYLOGFILE .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
- flow (orchestrator): Recorder take on the RØDE with the refresh logged; wake listener pause/resume around a take.

## Tasks
| # | Task | Scope (files/areas) | Bar | Status |
|---|------|---------------------|-----|--------|
| 01 | Device table refresh before open, open-stream guard, wake pause around takes, timing fields, version 0.1.20 | src/winwhisper/audio_inputs.py, recorder.py, wake_word_source.py, main.py, pyproject.toml, tests | build+tests+flow | done |
