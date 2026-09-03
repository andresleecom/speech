# MAP: hotfix - the in-app update hand-off never runs

**Goal:** Check for Updates on Windows installs the downloaded release and relaunches Speech, and leaves a log when it cannot.
**Base:** main @ 184b786 (0.1.21) · **Branch:** map/hotfix-updater-handoff · **Tier:** S
**Non-goals:** Sparkle/WinSparkle/Velopack, signed manifests, macOS/Linux update paths.

## Decisions
- D01 Orchestrator = fable-5; executor primary = grok-4.5, fallback codex gpt-5.6-sol, then Opus.
- D02 Root cause (measured 2026-09-03): `launch_installer` starts the hidden PowerShell with `DETACHED_PROCESS`; under that flag Windows PowerShell exits with code 0 without executing its command, so the installer never ran (today at 12:24 and on 2026-07-28). `CREATE_NO_WINDOW` alone runs the command.
- D03 Fix = drop `DETACHED_PROCESS`, keep `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`; add `/SUPPRESSMSGBOXES` and `/LOG=<updates>\install.log` to the installer; bound `Wait-Process` with a timeout; write a `handoff.log` with timestamps and the installer exit code; log every controller step at INFO; version 0.1.22.
- D04 Verification = unit tests plus a real hand-off on this machine: the fixed `launch_installer` against the running installed Speech.exe with the already-downloaded 0.1.21.42 installer (reinstalls the same version and relaunches).

## Constraints
- No new dependencies. Run Python as `env -u SSLKEYLOGFILE .venv/Scripts/python.exe`. Markdown: one sentence per line, no em dashes.

## Verify commands
- tests: `env -u SSLKEYLOGFILE .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`

## Tasks
| # | Task | Scope (files/areas) | Bar | Status |
|---|------|---------------------|-----|--------|
| 01 | Fix the installer hand-off, make it observable, bump to 0.1.22 | src/winwhisper/updater.py, update_controller.py, pyproject.toml, docs/troubleshooting.md, tests/test_updater.py, test_updater_install.py | build+tests+flow | done |
