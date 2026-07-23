# Task 02: Provision ephemeral CI signing credentials

You are the MAP executor (Grok CLI). Obey HARD RULES. No git. End with `## REPORT`.

## Goal
Make both macOS release matrix jobs import Developer ID credentials into an ephemeral keychain and run the build with mandatory signing/notarization. Ensure all temporary credential material is removed even when an earlier step fails.

## Context — read these first
- `.github/workflows/release.yml` — current ARM/Intel jobs and artifact upload.
- `scripts/build_macos.sh` — environment contract created by Task 01; do not edit it.
- `.map/PLAN.md` — locked decisions D02, D03, D05, and D07.

## Scope — you may edit
- `.github/workflows/release.yml`

## Out of scope — do not touch
- Build scripts, application code, dependencies, other jobs, publish behavior, and anything not listed under Scope.

## Required behavior
1. The macOS job must set `SPEECH_CODESIGN_IDENTITY` to the existing Developer ID identity and `SPEECH_NOTARIZE=1`.
2. Use these GitHub Actions secrets: `MACOS_DEVELOPER_ID_P12_BASE64`, `MACOS_DEVELOPER_ID_P12_PASSWORD`, `APPLE_NOTARY_KEY_P8`, `APPLE_NOTARY_KEY_ID`, and `APPLE_NOTARY_ISSUER_ID`.
3. Before building, fail closed on any empty secret without printing values; decode the P12 and write the P8 under `$RUNNER_TEMP`, with the P8 mode set to `600`.
4. Create a unique temporary keychain with a generated password, unlock it, import the P12/private key, set the Apple codesign partition list, put only that keychain on the user search list, and verify the expected identity is present.
5. Export `SPEECH_NOTARY_KEY` through `$GITHUB_ENV`, along with only the temporary paths needed by cleanup. Map key ID and issuer secrets to the build script's environment names.
6. Add an `if: always()` cleanup step after macOS artifact upload that deletes the temporary keychain and credential files without echoing credentials.
7. Do not alter Linux, Windows, release asset names, or publish behavior.

## Verify before reporting
Run: `ruby -e 'require "yaml"; YAML.load_file(".github/workflows/release.yml", aliases: true); puts "workflow yaml ok"'`
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
