# Task 01 follow-up: quote the installer arguments that carry paths

You are the MAP executor. Obey HARD RULES. No git. End with ## REPORT.

## Goal
The fixed hand-off now runs, but the real run on the owner's machine ended with `installer-exit=1` and no `install.log`. Cause: the `/LOG=<path>` element contains a space (`C:\Users\Andres Lee\AppData\Roaming\Speech\updates\install.log`) and PowerShell's `Start-Process -ArgumentList` joins elements with spaces without quoting, so Inno Setup received `/LOG=C:\Users\Andres` plus a stray token, could not create the log, and aborted with "Setup failed to initialize" (exit code 1) before installing. Do not redo the rest of task 01.

## Context - read these first
- `src/winwhisper/updater.py` `launch_installer`: `installer_args`, `argument_list = ",".join(json.dumps(arg) for arg in installer_args)`.
- PowerShell facts: a single-quoted PowerShell string is literal (only `''` escapes a quote); Inno accepts `/LOG="C:\path with spaces\install.log"`; `-FilePath` already handles spaces on its own.
- `tests/test_updater_install.py`: the tests that inspect the returned command string.

## Scope - you may edit
- `src/winwhisper/updater.py`, `tests/test_updater_install.py`

## Out of scope - do not touch
- Everything else.

## Steps
1. Build each `-ArgumentList` element as a PowerShell single-quoted literal (`'` + value with `'` doubled + `'`), and give the `/LOG=` element embedded double quotes around the path: the element must read `/LOG="C:\...\install.log"` so the joined command line keeps the path intact. Keep the plain flags as they are.
2. Tests: the returned command contains `'/LOG="` followed by the install log path and a closing `"'`; a path containing a single quote is doubled; add one real-process test (skipif not nt) that runs `powershell -NoProfile -Command` with `Start-Process -FilePath cmd.exe -ArgumentList <same quoting helper applied to '/c', 'echo', and a quoted path with a space> -Wait -RedirectStandardOutput <tmp>` and asserts the echoed line contains the full path, proving the quoting survives Start-Process.

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
