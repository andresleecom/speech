# Task 02: Enforce one Speech instance on POSIX

You are the MAP executor. Obey HARD RULES. No git. End with `## REPORT`.

## Goal
Make the existing single-instance guard work on macOS and Linux as well as Windows. A second POSIX process using the same app-data directory must exit cleanly, while unexpected lock setup errors retain the current fail-open behavior.

## Context — read these first
- `src/winwhisper/main.py` — `_acquire_single_instance()`, Windows mutex globals, and Task 01 watchdog changes that must be preserved.
- `tests/test_main.py` — current startup helper tests and platform monkeypatch patterns.
- `.map/PLAN.md` decisions D07-D09 are binding.

## Scope — you may edit
- `src/winwhisper/main.py`
- `tests/test_main.py`

## Out of scope — do not touch
- Task 01 microphone behavior, dependencies, packaging, settings schema, and every file not listed above.

## Required behavior
1. Preserve the existing Windows named-mutex path without semantic changes.
2. On non-Windows platforms, create a lock file under `app_data_dir()`, obtain `fcntl.flock(LOCK_EX | LOCK_NB)`, and retain its open handle globally for process lifetime.
3. Expected contention (`BlockingIOError`, including equivalent EACCES/EAGAIN cases) must close only the contender handle and return `False`.
4. Unexpected directory/open/import/lock errors must close any local handle and return `True` (fail open), matching existing policy.
5. A stale lock-file pathname must not block startup after the owning process/descriptor exits; do not rely on PID-file contents and do not unlink another process's lock.
6. Add deterministic POSIX tests for first acquisition, competing acquisition, release/reacquisition, and fail-open setup errors. Skip actual POSIX locking tests on Windows.

## Verify before reporting
Run:
- `/Users/andreslee/PythonProjects/speech/.venv/bin/python -m compileall -q src`
- `/Users/andreslee/PythonProjects/speech/.venv/bin/python -m pytest -q tests/test_main.py`
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
