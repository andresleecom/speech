# Task 01: Add local signing and notarization pipeline

You are the MAP executor (Grok CLI). Obey HARD RULES. No git. End with `## REPORT`.

## Goal
Teach the existing PyInstaller build to use a real Developer ID identity when supplied, then sign, notarize, staple, and verify the versioned DMG before producing stable-name copies and checksums. Preserve the current credential-free local build when signing variables are absent.

## Context — read these first
- `packaging/Speech.spec` — PyInstaller EXE/BUNDLE configuration and stable bundle ID.
- `scripts/build_macos.sh` — current app/DMG build and checksum ordering.
- `.map/PLAN.md` — locked decisions D02-D06.

## Scope — you may edit
- `packaging/Speech.spec`
- `scripts/build_macos.sh`

## Out of scope — do not touch
- `.github/workflows/release.yml`
- Tests, dependencies, bundle ID, app behavior, and anything not listed under Scope.

## Required behavior
1. Read `SPEECH_CODESIGN_IDENTITY` in the spec and pass it to PyInstaller's `EXE` as `codesign_identity`; an empty value must retain ad-hoc local builds. Do not add entitlements.
2. In the shell script support `SPEECH_NOTARIZE=0|1` (default `0`) plus `SPEECH_NOTARY_KEY`, `SPEECH_NOTARY_KEY_ID`, and `SPEECH_NOTARY_ISSUER`.
3. Fail before building if notarization is enabled without a non-empty signing identity, readable key file, key ID, or issuer. Reject invalid `SPEECH_NOTARIZE` values.
4. With a signing identity, verify the finished app using strict/deep `codesign` verification before packaging.
5. Create the versioned DMG, sign and verify it when an identity is present, then when notarization is enabled run `xcrun notarytool submit ... --wait`, `xcrun stapler staple`, and `xcrun stapler validate`.
6. Only after signing/notarization, copy the versioned DMG to the stable filename and calculate both checksums.
7. Ensure temporary staging cleanup also occurs on failure. Never print credential contents.

## Verify before reporting
Run: `bash -n scripts/build_macos.sh`
Run: `/Users/andreslee/PythonProjects/speech/.venv/bin/python -m pytest -q`
Paste concise output in your REPORT under PROOF.

HARD RULES — violating any of these means your work is discarded:
- NO git commands of any kind (no commit, branch, push, reset, checkout, stash).
- NO dependency changes: no package installs, no lockfile edits, no tool installs.
  If your solution needs a library the module does not declare, STOP and say so
  in NOTES instead of writing code that cannot compile.
- Edit ONLY within the scope listed above. If the fix requires touching anything
  else, STOP and explain in your REPORT instead of doing it.
- If blocked or uncertain, STOP and report — do not improvise around the spec.
- End your output with:
  ## REPORT
  STATUS: done | blocked
  FILES TOUCHED: <list>
  PROOF: <output of the verification commands you were asked to run>
  NOTES: <≤10 lines: decisions made, anything the reviewer must know>
