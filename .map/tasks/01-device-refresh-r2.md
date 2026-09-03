# Task 01 follow-up: un-pin the version test

You are the MAP executor (Grok CLI). Obey HARD RULES. No git. End with ## REPORT.

## Goal
`tests/test_main.py::test_pyproject_version_is_0_1_19` asserts a literal version and fails on every bump. Replace it with a format check so the suite passes with `pyproject.toml` at `0.1.20` and at any future version. Do not touch the feature work already in the working tree.

## Context - read these first
- `tests/test_main.py`: the pinned test near the end of the file.
- `pyproject.toml` now says `version = "0.1.20"`.

## Scope - you may edit
- `tests/test_main.py` only.

## Out of scope - do not touch
- Everything else.

## Steps
1. Rename the test to `test_pyproject_version_is_three_part_semver` and assert the version matches `^\d+\.\d+\.\d+$` (read from `pyproject.toml` the same way the current test does).

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
