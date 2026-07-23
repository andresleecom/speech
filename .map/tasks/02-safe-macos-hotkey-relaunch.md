# Task 02: Save macOS hotkeys without restarting pynput in-process

You are the MAP executor (Grok CLI). Obey HARD RULES. No git. End with
`## REPORT`.

## Goal

Fix the reproducible macOS crash when a user saves changed hotkeys. Validate and
persist the new profile, then relaunch a packaged Speech app only after the
AppKit settings modal has unwound. Never stop/start/replace the pynput listener
inside the macOS save callback. Preserve existing live rebinding on Windows and
Linux.

## Confirmed crash evidence

`Speech-2026-07-23-125434.ips` is a real Speech crash immediately after a hotkey
save. The faulting pynput worker thread is:

`_dispatch_assert_queue_fail -> dispatch_assert_queue ->`
`islGetInputSourceListWithAdditions -> TSMGetInputSourceProperty -> ctypes ->`
`thread_run`

The app log shows a second Input Monitoring check at the save time, matching
`AppController.set_hotkeys()` stopping the old manager and starting a new
listener from the settings callback. This is not a signing crash.

## Context — read first

- `.map/PLAN.md` decisions D07-D09
- `src/winwhisper/main.py`, especially `set_hotkeys`, `stop`, and `exit_app`
- `src/winwhisper/hotkey_settings_window.py`, especially the macOS modal callback
- `tests/test_overlay_flow.py` hotkey save tests and fakes
- `docs/configuration.md` Hotkeys section

## Frozen design

1. Keep normalization/duplicate validation exactly as today.
2. On macOS:
   - Do not instantiate a replacement `HotkeyManager`.
   - Do not call `start()` or `stop()` on the current manager from
     `set_hotkeys`.
   - Assign normalized settings and save them. If saving fails, restore the
     previous in-memory value and raise `HotkeyConfigurationError`; do not
     schedule a relaunch.
3. For a frozen executable located at
   `<name>.app/Contents/MacOS/<executable>`:
   - Start a detached `/bin/sh` helper before scheduling shutdown.
   - Pass the current PID and `.app` path as separate argv values. Do not
     interpolate either value into shell source.
   - The helper waits until the current PID is gone, then executes
     `/usr/bin/open -n "$app_path"`.
   - Queue `self.exit_app` onto AppKit's main operation queue. It must run only
     after `set_hotkeys` returns and the modal's current operation can unwind.
   - Notify/log that settings were saved and Speech is restarting.
4. In a source/non-frozen run, with an invalid bundle path, if helper launch
   fails, or if the AppKit operation cannot be queued:
   - Keep the successfully saved settings.
   - Do not exit immediately.
   - Log and notify the user to quit and reopen Speech manually.
5. Existing Windows/Linux live rebind, registration-conflict rollback, and
   save-failure behavior must remain unchanged.
6. Keep platform imports lazy; add no dependencies. Do not launch a real app,
   AppKit window, or helper during tests.

## Required tests

- A packaged macOS save persists the normalized profile while the original
  manager remains running during the callback; no replacement manager is
  created. It launches the helper and queues (but does not synchronously call)
  shutdown.
- Invoking the captured queued operation later performs normal shutdown; this
  distinguishes post-modal shutdown from in-callback listener mutation.
- The helper uses an argv-safe `.app` path containing spaces and detached,
  closed-stdio process options; PID/path are not shell-interpolated.
- Source/non-frozen mode and helper/queue failures retain the saved settings and
  request a manual restart without exiting.
- macOS save failure restores prior settings and neither launches nor schedules
  anything.
- Existing non-macOS live-rebind tests continue passing.

## Allowed files

- `src/winwhisper/main.py`
- `tests/test_overlay_flow.py`
- `docs/configuration.md`

## Verify

Run:

`PYTHONPATH=src /Users/andreslee/PythonProjects/speech/.venv/bin/python -m pytest -q tests/test_overlay_flow.py`

`PYTHONPATH=src /Users/andreslee/PythonProjects/speech/.venv/bin/python -m compileall -q src`

HARD RULES:

- NO git commands of any kind.
- NO dependency changes or installs.
- Edit only the three allowed files.
- Do not launch AppKit, Speech, `open`, or a real helper process.
- If blocked or uncertain, stop and report.
- End with:

  `## REPORT`

  `STATUS: done | blocked`

  `FILES TOUCHED: <list>`

  `PROOF: <verification output>`

  `NOTES: <at most 10 lines>`
