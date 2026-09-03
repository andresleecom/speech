# Task 01: make the Windows update hand-off actually run, and leave a trail

You are the MAP executor. Obey HARD RULES. No git. End with ## REPORT.

## Goal
`launch_installer` in `src/winwhisper/updater.py` starts a hidden PowerShell that waits for Speech to exit, runs the downloaded Inno installer silently, and relaunches Speech. Measured today: with `DETACHED_PROCESS` in `creationflags`, `powershell.exe` exits with code 0 without executing the command at all, so the installer never runs and nothing is logged. With `CREATE_NO_WINDOW` (plus `CREATE_NEW_PROCESS_GROUP`) and no `DETACHED_PROCESS`, the same command runs. Fix the flags, make the hand-off observable, and bump the version to 0.1.22.

## Context - read these first
- `src/winwhisper/updater.py`: `launch_installer(installer_path, wait_for_pid, relaunch_path)` (~line 314-370), `download_update`, `current_app_executable`.
- `src/winwhisper/update_controller.py`: `_check_for_updates_worker` (~line 65-105) downloads, calls `launch_installer(installer_path, wait_for_pid=os.getpid(), relaunch_path=...)`, then `_exit_app()`; it logs nothing on the success path.
- `installer/Speech.iss`: `CloseApplications=yes`, the `[Run]` entry is `skipifsilent`, so the relaunch must come from the hand-off.
- `docs/troubleshooting.md`.
- Tests: `tests/test_updater.py`, `tests/test_updater_install.py` (monkeypatched `subprocess.Popen` pattern in `test_installer_relaunches_speech_after_a_silent_install`).

## Scope - you may edit
- `src/winwhisper/updater.py`, `src/winwhisper/update_controller.py`, `pyproject.toml`, `docs/troubleshooting.md`
- `tests/test_updater.py`, `tests/test_updater_install.py`

## Out of scope - do not touch
- `installer/Speech.iss`, workflows, everything else.

## Steps
1. `updater.py` `launch_installer`: creation flags become `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP` (never `DETACHED_PROCESS`), with a comment stating why. Installer arguments gain `/SUPPRESSMSGBOXES` and `/LOG=<installer_path.parent>\install.log`. The PowerShell command: `Wait-Process -Id <pid> -Timeout 60 -ErrorAction SilentlyContinue`; append a timestamped `waiting`/`launching`/`installer-exit=<code>`/`relaunching` line to `<installer_path.parent>\handoff.log` at each step (`Out-File -Append`); `Start-Process ... -PassThru -Wait` and record `$p.ExitCode`; relaunch as today and log it. Return the command string (or a small dataclass) so tests can assert on it without running PowerShell. Keep the non-Windows branch as is.
2. `update_controller.py`: INFO log lines for the version found, download completed (bytes and seconds), installer path, our pid, relaunch path, and `Exiting so the installer can replace the binaries.`; WARNING when `relaunch_path` is None (source run) explaining the app will not reopen.
3. `pyproject.toml`: version `0.1.22`.
4. `docs/troubleshooting.md`: a section "Update downloaded but nothing happened" pointing at `%APPDATA%\Speech\updates\handoff.log` and `install.log`, and the manual download fallback. One sentence per line, no em dashes.
5. Tests: `launch_installer` under a fake `subprocess.Popen` asserts the flags exclude `DETACHED_PROCESS` and include `CREATE_NO_WINDOW`, the args include `/SUPPRESSMSGBOXES` and `/LOG=`, and the command mentions `Wait-Process -Id`, `-Timeout`, `handoff.log`, `-PassThru`, and the relaunch path; keep the existing relaunch and source-run tests green. Add one real-process test marked `skipif(os.name != "nt")` that launches `powershell -NoProfile -WindowStyle Hidden -Command "'ok' | Out-File <tmp marker>"` with the new flags through the same helper the code uses and asserts the marker appears within 20 s.

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
