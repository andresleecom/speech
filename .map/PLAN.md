# MAP: macOS permission onboarding and safe hotkey updates

**Goal:** Speech guides macOS users through every required permission, validates readiness, records with the signed build, and saves hotkey changes without crashing.
**Base:** main@332e1c3 · **Branch:** map/macos-permission-onboarding · **Tier:** S
**Non-goals:** Replace pynput with a native event-tap backend; redesign non-macOS settings; add new dependencies; publish a release before the PR reaches main.

## Decisions
- D01 Orchestrator = current Codex session; Fable 5 is unavailable.
- D02 Executor primary = Grok CLI `grok-4.5`; fallback = Codex Sol, then Opus 4.8.
- D03 Add a native AppKit “Set up Speech” window with Microphone, Input Monitoring, and Accessibility status rows, permission/settings actions, recheck, and relaunch guidance.
- D04 Show setup automatically whenever a required permission is missing and expose “Permissions...” in the macOS tray menu; keep the tray usable while gating only affected features.
- D05 Distinguish user-fixable permission state from a missing audio-input entitlement, which is a build defect.
- D06 Sign the macOS executable with `com.apple.security.device.audio-input = true` and make the build verify that entitlement.
- D07 On macOS, validate and persist edited hotkeys, then relaunch the packaged app; never stop/start the pynput listener from the settings modal.
- D08 Windows and Linux retain live hotkey rebinding and existing behavior.
- D09 A push to main creates the release through the existing workflow; no manual tag or release asset publication.

## Constraints
- Use existing PyObjC/AppKit patterns and lazy platform imports.
- No new runtime or development dependencies.
- Permission APIs must be testable without invoking real TCC prompts.
- Never claim the app can grant macOS permissions itself; it may request, deep-link, and recheck.
- Preserve current signed/notarized release automation and cross-platform tests.

## Verify commands
- build/typecheck: `PYTHONPATH=src /Users/andreslee/PythonProjects/speech/.venv/bin/python -m compileall -q src`
- tests: `PYTHONPATH=src /Users/andreslee/PythonProjects/speech/.venv/bin/python -m pytest -q`
- flow check: build Speech.app, inspect its code-signing entitlement, then launch the permissions window and exercise recheck/settings actions on macOS.

## Tasks
| # | Task | Scope (files/areas) | Bar | Status |
|---|------|---------------------|-----|--------|
| 01 | Add permission assistant and audio entitlement | macOS permission modules/UI, controller/tray integration, package/build validation, focused tests/docs | build+tests+flow | done |
| 02 | Make macOS hotkey saves relaunch safely | controller/hotkey settings behavior and focused tests/docs | build+tests+flow | pending |

Bar legend: build = diff review + build/typecheck · +tests = also relevant tests ·
+flow = also drive the affected flow.

Status values: `pending` · `done` · `blocked` · `takeover`.
