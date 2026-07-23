# Task 01 takeover: Ship a correct macOS permission assistant

You are the MAP takeover executor (Codex Sol). Two Grok attempts failed review. Implement from the clean base, obey HARD RULES, and end with ## REPORT.

## Goal
Implement the complete original contract in `01-macos-permission-assistant.md`, informed by `01-macos-permission-assistant-r2.md`. Add the native permission validator, feature gating, microphone entitlement, build verification, tests, and troubleshooting docs. The workspace contains no surviving product-code attempt.

## Context — read these first
- `.map/PLAN.md`
- `.map/tasks/01-macos-permission-assistant.md`
- `.map/tasks/01-macos-permission-assistant-r2.md`
- `src/winwhisper/main.py`, `tray.py`, `hotkeys.py`, `recorder_mac.py`
- `src/winwhisper/hotkey_settings_window.py` for main-queue AppKit conventions
- `packaging/Speech.spec`, `scripts/build_macos.sh`

## Rejection evidence that must become tests
1. A valid signed executable with no entitlement produces `codesign` exit 0, empty stdout, and only `Executable=...` on stderr. That is definitively `misconfigured`/False, not unknown. Nonzero/unavailable codesign may be unknown. An explicit false is also misconfigured.
2. The prior live 520px render overlapped `Status:` and detail text. Use non-overlapping frames (minimum 4px vertical separation) and concise/wrapped copy. Header copy must also fit. Avoid duplicate delegates.
3. Fresh Input Monitoring and Accessibility states are indistinguishable from denial. A user click must call `CGRequestListenEventAccess` / `AXIsProcessTrustedWithOptions` first; if still missing, deep-link to Settings. Checks never prompt.
4. Microphone Allow must use AVFoundation completion asynchronously and return to AppKit immediately; callback UI changes must hop to the main queue.
5. Do not start or restart pynput from a permission-window callback. Startup may start it only if permissions were already ready; otherwise show relaunch guidance. Task 02 owns controlled relaunch.

## Implementation constraints
- Use the exact allowed files from the original packet; no new dependencies.
- Prefer `/usr/bin/codesign --display --entitlements - --xml` plus `/usr/bin/plutil -convert json -o - -` and Python `json`; local Python's `plistlib/pyexpat` is broken. Do not add a custom XML parser.
- Runtime entitlement inspection should cache per process. In a frozen signed app, no entitlements means False.
- Keep AppKit/AVFoundation/Quartz/ApplicationServices imports lazy and non-macOS behavior unchanged.
- Add unit tests for all five rejection cases plus startup/recording/tray integration.

## Verify before reporting
Run:
`PYTHONPATH=src /Users/andreslee/PythonProjects/speech/.venv/bin/python -m compileall -q src`
`PYTHONPATH=src /Users/andreslee/PythonProjects/speech/.venv/bin/python -m pytest -q`
Paste output in REPORT.

HARD RULES — violating any of these means your work is discarded:
- NO git commands of any kind (no commit, branch, push, reset, checkout, stash).
- NO dependency changes: no package installs, no lockfile edits, no tool installs.
- Edit ONLY within the scope listed in the original packet. If anything else is required, STOP and report.
- If blocked or uncertain, STOP and report — do not improvise around the spec.
- End your output with:
  ## REPORT
  STATUS: done | blocked
  FILES TOUCHED: <list>
  PROOF: <output of the verification commands you were asked to run>
  NOTES: <≤10 lines: decisions made, anything the reviewer must know>
