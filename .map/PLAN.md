# MAP: Sign and notarize Speech for macOS

**Goal:** Every published macOS DMG contains a Developer ID-signed Speech.app and is notarized, stapled, and verified before checksums are generated.
**Base:** fix/macos-native-audio@4d5d4b6 · **Branch:** map/speech-signing-notarization · **Tier:** S
**Non-goals:** Mac App Store distribution, Windows signing, rotating Apple credentials, pushing to main, or publishing a release.

## Decisions
- D01 Orchestrator = current Codex session; executor primary = Grok 4.5 — Fable 5 is unavailable in this session.
- D02 Distribution stays as direct-download DMGs signed with `Developer ID Application: Launcher S de RL de CV (XB92PXFQ2L)`.
- D03 Local developer builds remain possible without credentials; notarization is opt-in locally and mandatory in the release workflow.
- D04 PyInstaller receives the real signing identity so it signs nested Mach-O code with hardened runtime; no extra entitlements are added unless the signed runtime smoke proves one is required.
- D05 Notarization uses `notarytool` API-key authentication; credentials must only come from local files or GitHub Actions secrets.
- D06 The versioned DMG is signed, notarized, and stapled before copying the stable filename and calculating either checksum.
- D07 GitHub-hosted ARM and Intel jobs import the Developer ID P12 into an ephemeral keychain and delete all temporary credential files in an always-running cleanup step.

## Constraints
- Never print, commit, or embed P12/P8 contents or passwords.
- Preserve bundle identifier `com.andreslee.speech` and existing unsigned local-build behavior.
- Both arm64 and Intel release artifacts must follow the same signing and notarization path.
- Fail closed when notarization is requested but any credential or signing identity is missing.
- Do not push or trigger the release workflow during this MAP.

## Verify commands
- tests: `/Users/andreslee/PythonProjects/speech/.venv/bin/python -m pytest -q`
- shell: `bash -n scripts/build_macos.sh`
- workflow: `ruby -e 'require "yaml"; YAML.load_file(".github/workflows/release.yml"); puts "workflow yaml ok"'`
- flow check: build locally with the Developer ID identity, run `--version` and `--diagnostics`, verify the app and DMG signatures, submit the DMG with `notarytool --wait`, staple it, and validate it.

## Tasks
| # | Task | Scope (files/areas) | Bar | Status |
|---|------|---------------------|-----|--------|
| 01 | Add local signing and notarization pipeline | `packaging/Speech.spec`, `scripts/build_macos.sh`, focused tests if needed | build+tests+flow | done |
| 02 | Provision ephemeral CI signing credentials | `.github/workflows/release.yml` | build+tests | done |

Bar legend: build = diff review + build/typecheck · +tests = also relevant tests ·
+flow = also drive the affected flow.

Status values: `pending` · `done` · `blocked` · `takeover`.
