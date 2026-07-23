# Task 01: Add macOS permission assistant and audio entitlement

You are the MAP executor (Grok CLI). Obey HARD RULES. No git. End with ## REPORT.

## Goal
Add a native, non-modal macOS “Set up Speech” window that visibly validates Microphone, Input Monitoring, and Accessibility. It must guide users through Apple’s permission flows, recheck state, distinguish a malformed build from a user-denied permission, and prevent silent feature failure. Add and verify the hardened-runtime microphone entitlement.

## Context — read these first
- `src/winwhisper/main.py` — startup, recording/test entry points, and controller windows.
- `src/winwhisper/hotkeys.py` — current Accessibility/Input Monitoring APIs.
- `src/winwhisper/recorder_mac.py` — current microphone authorization flow.
- `src/winwhisper/hotkey_settings_window.py` — AppKit main-queue/window pattern.
- `src/winwhisper/tray.py` — menu integration.
- `packaging/Speech.spec`, `scripts/build_macos.sh` — signed bundle creation.
- `.map/PLAN.md` — frozen decisions and constraints.

## Scope — you may edit
- `src/winwhisper/macos_permissions.py` (new)
- `src/winwhisper/permission_setup_window.py` (new)
- `src/winwhisper/main.py`
- `src/winwhisper/tray.py`
- `packaging/Speech.spec`
- `packaging/Speech.entitlements` (new)
- `scripts/build_macos.sh`
- `tests/test_macos_permissions.py` (new)
- `tests/test_permission_setup_window.py` (new)
- `tests/test_overlay_flow.py`
- `tests/test_tray.py`
- `tests/test_macos_packaging.py` (new, if useful)
- `docs/troubleshooting.md`

## Required behavior
1. Keep platform imports lazy. Put testable permission state/check/request/open-settings logic in `macos_permissions.py`; checks never prompt.
2. Model `granted`, `not_determined`/`missing`, `denied`/`restricted`, and `misconfigured` where meaningful. In a frozen app, a missing `com.apple.security.device.audio-input` entitlement must report build misconfiguration, not blame the user. Development runs may treat entitlement availability as unknown/ready.
3. Build a retained, non-modal AppKit window with three rows: purpose, live status, and appropriate Allow/Open Settings action. Include Recheck and Close/Done. Keep it usable while System Settings is open.
4. On macOS startup, automatically show setup when anything is not ready. Keep the tray alive; start global hotkeys only when Accessibility and Input Monitoring are ready. If manual recording or microphone test lacks microphone readiness, open setup and return a clear error instead of failing silently.
5. Add macOS-only `Permissions...` to the tray. Other platforms must not change.
6. Add `com.apple.security.device.audio-input = true` to the PyInstaller executable signing configuration. Make `build_macos.sh` fail if the built executable lacks it.
7. Do not grant permissions, reset TCC, relaunch the app, or add dependencies. Task 02 owns relaunch behavior.
8. Add focused tests for pure state mapping/actions, startup and feature gating, tray visibility/action, UI main-queue scheduling, and packaging entitlement wiring. Update troubleshooting text.

## Verify before reporting
Run:
`PYTHONPATH=src /Users/andreslee/PythonProjects/speech/.venv/bin/python -m compileall -q src`
`PYTHONPATH=src /Users/andreslee/PythonProjects/speech/.venv/bin/python -m pytest -q`
Paste the output in your REPORT under PROOF.

HARD RULES — violating any of these means your work is discarded:
- NO git commands of any kind (no commit, branch, push, reset, checkout, stash).
- NO dependency changes: no package installs, no lockfile edits, no tool installs.
- Edit ONLY within the scope listed above. If the fix requires touching anything else, STOP and explain in your REPORT instead of doing it.
- If blocked or uncertain, STOP and report — do not improvise around the spec.
- End your output with:
  ## REPORT
  STATUS: done | blocked
  FILES TOUCHED: <list>
  PROOF: <output of the verification commands you were asked to run>
  NOTES: <≤10 lines: decisions made, anything the reviewer must know>
