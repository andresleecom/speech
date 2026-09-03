from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_macos_executable_is_wired_to_audio_input_entitlement():
    spec = (ROOT / "packaging" / "Speech.spec").read_text(encoding="utf-8")
    entitlements = (ROOT / "packaging" / "Speech.entitlements").read_text(
        encoding="utf-8"
    )

    assert "entitlements_file=ENTITLEMENTS_FILE" in spec
    assert "Speech.entitlements" in spec
    assert "<key>com.apple.security.device.audio-input</key>" in entitlements
    assert "<true/>" in entitlements


def test_macos_bundle_uses_the_speech_icns():
    spec = (ROOT / "packaging" / "Speech.spec").read_text(encoding="utf-8")

    assert 'icon=str(ROOT / "packaging" / "macos" / "speech.icns")' in spec
    assert (ROOT / "packaging" / "macos" / "speech.icns").is_file()


def test_windows_exe_uses_the_speech_ico():
    spec = (ROOT / "packaging" / "Speech.spec").read_text(encoding="utf-8")

    assert 'packaging" / "windows" / "speech.ico"' in spec
    assert "icon=EXE_ICON" in spec
    assert (ROOT / "packaging" / "windows" / "speech.ico").is_file()


def test_macos_build_verifies_boolean_entitlement_without_grep_or_plistlib():
    script = (ROOT / "scripts" / "build_macos.sh").read_text(encoding="utf-8")

    assert "/usr/bin/codesign --display --entitlements - --xml" in script
    assert "/usr/bin/plutil -convert json" in script
    assert 'data.get("com.apple.security.device.audio-input") is True' in script
    assert "plistlib" not in script
    assert "grep" not in script


def test_release_workflow_verifies_notarized_macos_artifact_before_upload():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    verifier = (ROOT / "scripts" / "verify_macos_release.sh").read_text(
        encoding="utf-8"
    )

    verify_step = workflow.index("- name: Verify macOS release trust")
    upload_step = workflow.index("- name: Upload macOS release assets")

    assert verify_step < upload_step
    assert 'bash scripts/verify_macos_release.sh "$DMG" XB92PXFQ2L' in workflow
    assert "hdiutil verify" in verifier
    assert "codesign --verify --deep --strict" in verifier
    assert "xcrun stapler validate" in verifier
    assert "spctl --assess --type execute" in verifier
    assert "flags=.*runtime" in verifier
    assert "com.apple.security.get-task-allow" in verifier
