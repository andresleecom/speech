# Task 01 takeover correction: make the permission window reopen safely

You are the MAP takeover executor (Codex Sol) correcting a review defect in your
Task 01 implementation. Work only in the allowed files below and end with
`## REPORT`.

## Confirmed rejection evidence

The orchestrator verified both facts without opening a window:

- `NSWindowDelegate` exposes `windowWillClose:`; it does not expose
  `windowDidClose:`.
- Defining the nested `PermissionWindowDelegate` a second time raises:
  `objc.error: PermissionWindowDelegate is overriding existing Objective-C class`.

The current code therefore cannot reliably clear its retained state or reopen
the permissions assistant after it is closed.

## Required fix

- Define/cache the PyObjC delegate class once per process, lazily, rather than
  inside every `_build_window` call.
- Give each delegate instance its own owner reference so multiple
  `PermissionSetupWindow` instances remain correct.
- Implement the actual `windowWillClose_` selector.
- On close, clear the owner's `_window`, `_delegate`, `_row_views`, and
  `_done_button` state; break any owner/delegate reference cycle.
- Keep all AppKit imports lazy and preserve the existing non-modal/main-queue
  behavior.
- Add a pure unit regression test proving:
  1. requesting the delegate class twice returns the same class and does not
     redefine an Objective-C class;
  2. `windowWillClose_` clears retained state and allows the owner to build
     again;
  3. no `windowDidClose_` selector is used.
- Do not instantiate `NSApplication`, `NSWindow`, or run any live/headless
  AppKit smoke in this task.

## Allowed files

- `src/winwhisper/permission_setup_window.py`
- `tests/test_permission_setup_window.py`

## Verify

Run:

`PYTHONPATH=src /Users/andreslee/PythonProjects/speech/.venv/bin/python -m pytest -q tests/test_permission_setup_window.py`

`PYTHONPATH=src /Users/andreslee/PythonProjects/speech/.venv/bin/python -m compileall -q src`

HARD RULES:

- NO git commands of any kind.
- NO dependency changes or installs.
- Edit only the two allowed files.
- Do not launch a real AppKit application/window.
- If blocked, stop and report.
- End with:

  `## REPORT`

  `STATUS: done | blocked`

  `FILES TOUCHED: <list>`

  `PROOF: <verification output>`

  `NOTES: <at most 10 lines>`
