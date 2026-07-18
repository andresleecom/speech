# Task 01: Make microphone shutdown fail-safe

You are the MAP executor. Obey HARD RULES. No git. End with `## REPORT`.

## Goal
Prevent a blocking PortAudio/CoreAudio stop from leaving Speech and the microphone stuck. Normal stops must abort and close the input stream safely; a watchdog must hard-exit only when the microphone-stop phase itself exceeds five seconds, never merely because transcription is slow.

## Context — read these first
- `src/winwhisper/recorder.py` — current dictation and microphone-test stream lifecycle.
- `src/winwhisper/main.py` — dictation worker, shutdown path, and existing slow-transcription watcher.
- `tests/test_recorder.py` and `tests/test_overlay_flow.py` — established fakes and controller tests.
- `.map/PLAN.md` decisions D03-D06 are binding.

## Scope — you may edit
- `src/winwhisper/recorder.py`
- `src/winwhisper/main.py`
- `tests/test_recorder.py`
- `tests/test_overlay_flow.py`

## Out of scope — do not touch
- Instance-lock behavior (Task 02).
- Model loading, dependencies, packaging, settings, release code, and every file not listed above.

## Required behavior
1. For both recorder classes, call `abort(ignore_errors=False)` and always attempt `close(ignore_errors=True)`; preserve actionable `RecorderError` behavior when abort fails.
2. Create explicit per-stop completion state before the dictation worker starts and set it immediately when `stop_recording()` returns or raises.
3. A five-second watchdog observes only that completion state. On timeout, log a critical error, best-effort notify the user, then call a small monkeypatchable boundary that invokes `os._exit(70)`.
4. Shutdown must not claim `Speech stopped` while microphone shutdown is still unresolved. It may wait up to the same deadline and then use the same hard-exit boundary.
5. Once microphone stop completes, arbitrarily long transcription must never trigger this watchdog.
6. Add deterministic tests with no live microphone and no real process exit: normal abort/close, abort error cleanup, blocked stop timeout, and slow transcription after a successful stop.

## Verify before reporting
Run:
- `/Users/andreslee/PythonProjects/speech/.venv/bin/python -m compileall -q src`
- `/Users/andreslee/PythonProjects/speech/.venv/bin/python -m pytest -q tests/test_recorder.py tests/test_overlay_flow.py`
- `/Users/andreslee/PythonProjects/speech/.venv/bin/python -m pytest -q`
Paste the outputs in your REPORT under PROOF.

HARD RULES - violating any of these means your work is discarded:
- NO git commands of any kind (no commit, branch, push, reset, checkout, stash).
- NO dependency changes: no package installs, no lockfile edits, no tool installs.
- Edit ONLY within the scope listed above. If the fix requires touching anything
  else, STOP and explain in your REPORT instead of doing it.
- If blocked or uncertain, STOP and report - do not improvise around the spec.
- End your output with:
  ## REPORT
  STATUS: done | blocked
  FILES TOUCHED: <list>
  PROOF: <output of the verification commands you were asked to run>
  NOTES: <≤10 lines: decisions made, anything the reviewer must know>
