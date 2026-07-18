# MAP: Microphone safety and single-instance enforcement

**Goal:** Speech releases a stuck microphone deterministically and prevents duplicate app instances on every supported desktop platform.
**Base:** `origin/main@a36b5e39c89ad7264d026549620a8dcde121703a` · **Branch:** `map/microphone-safety` · **Tier:** S
**Non-goals:** Model-download resilience, dependency locking, signing/notarization, auto-update work, clipboard behavior, or unrelated cleanup.

## Decisions
- D01 Orchestrator = Codex fallback because Fable 5 is unavailable in this host.
- D02 Executor primary = Grok CLI `grok-4.5`; fallback = Codex `gpt-5.6-sol`.
- D03 Replace blocking graceful input-stream stop with `abort(ignore_errors=False)` and always attempt `close(ignore_errors=True)` for dictation and microphone tests.
- D04 A 5-second watchdog covers only microphone shutdown, never model loading or transcription.
- D05 If microphone shutdown remains blocked after 5 seconds, log the failure, notify when possible, and call `os._exit(70)` so macOS releases CoreAudio resources. Do not auto-relaunch in this patch.
- D06 Track watchdog state explicitly so a completed microphone stop cannot be mistaken for a long transcription.
- D07 macOS/Linux use a non-blocking `fcntl.flock` held for process lifetime; Windows keeps its existing named mutex.
- D08 Expected lock contention rejects the second instance; unexpected lock setup errors retain the existing fail-open behavior.
- D09 Task executors = Codex `gpt-5.6-sol`; Grok CLI 0.2.103 rejected the required `grok-4.5` model id before editing any file.

## Constraints
- Preserve current Windows behavior and public settings.
- No dependency or packaging changes.
- Never hard-exit in tests; monkeypatch the exit boundary.
- Do not log dictated text or audio-derived content.
- Keep task diffs limited to the files named in each packet.

## Verify commands
- build/typecheck: `/Users/andreslee/PythonProjects/speech/.venv/bin/python -m compileall -q src`
- tests: `/Users/andreslee/PythonProjects/speech/.venv/bin/python -m pytest -q`
- flow check: focused tests must simulate a blocked PortAudio stop and competing POSIX lock acquisition without using a live microphone or terminating the test runner.

## Tasks
| # | Task | Scope (files/areas) | Bar | Status |
|---|------|---------------------|-----|--------|
| 01 | Make microphone shutdown fail-safe | `recorder.py`, `main.py`, recorder/controller tests | build+tests+flow | pending |
| 02 | Enforce one instance on POSIX | `main.py`, `test_main.py` | build+tests+flow | pending |

Bar legend: build = diff review + build/typecheck · +tests = also relevant tests ·
+flow = also drive the affected flow.

Status values: `pending` · `done` · `blocked` · `takeover`.
