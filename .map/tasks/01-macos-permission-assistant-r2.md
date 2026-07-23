# Task 01 retry: Permission actions must work for fresh installs

You are the MAP executor (Grok CLI). Obey HARD RULES. No git. End with ## REPORT.

## Goal
Reimplement Task 01 from `01-macos-permission-assistant.md`. The first attempt was discarded because green tests hid broken first-run permission actions and a blocking AppKit path. Preserve the original scope and behavior, with every defect below fixed and covered by tests.

## Context — read these first
- `.map/tasks/01-macos-permission-assistant.md` — full original contract and allowed files.
- `.map/PLAN.md` — frozen decisions.
- `src/winwhisper/hotkeys.py:530-575` — existing request APIs that put fresh installs into Accessibility/Input Monitoring flows.
- `src/winwhisper/recorder_mac.py:500-545` — microphone authorization semantics.
- `src/winwhisper/hotkey_settings_window.py:60-95` — AppKit scheduling pattern.
- `packaging/Speech.spec`, `scripts/build_macos.sh` — signing/build.

## Defects that caused rejection
1. `CGPreflightListenEventAccess == false` and `AXIsProcessTrusted == false` cannot distinguish first use from denial. The prior UI classified both as “Open Settings” and never called `CGRequestListenEventAccess` / `AXIsProcessTrustedWithOptions`, so a fresh app might never be registered in the privacy list. A user click must invoke the request API first; if still unready, deep-link to the correct pane. Checks themselves must remain prompt-free.
2. The microphone Allow button called a function that waited up to 60 seconds on the AppKit main queue. Request microphone access asynchronously (worker or completion handler) and schedule the resulting UI refresh back onto the main queue. The window must never block while the user answers TCC.
3. Add tests proving fresh Input Monitoring and Accessibility actions call their request API, and proving microphone Allow returns immediately while its completion/recheck happens asynchronously.
4. Permission-row detail strings were visibly clipped. Use concise text and/or real multiline wrapping; verify a denied/missing-state render is legible within the 520px window.
5. Replace deprecated `codesign ... --entitlements :-` and string grep parsing. Use `codesign --display --entitlements - --xml` and parse the plist (Python `plistlib` is available) both at runtime and in `build_macos.sh`. Fail unless the value is exactly boolean true.

## Scope
Exactly the files allowed by the original packet. No dependencies, README changes, TCC resets, relaunch implementation, or non-macOS behavior changes.

## Verify before reporting
Run:
`PYTHONPATH=src /Users/andreslee/PythonProjects/speech/.venv/bin/python -m compileall -q src`
`PYTHONPATH=src /Users/andreslee/PythonProjects/speech/.venv/bin/python -m pytest -q`
Paste the output in your REPORT under PROOF.

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
