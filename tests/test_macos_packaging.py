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


def test_macos_build_verifies_boolean_entitlement_without_grep_or_plistlib():
    script = (ROOT / "scripts" / "build_macos.sh").read_text(encoding="utf-8")

    assert "/usr/bin/codesign --display --entitlements - --xml" in script
    assert "/usr/bin/plutil -convert json" in script
    assert 'data.get("com.apple.security.device.audio-input") is True' in script
    assert "plistlib" not in script
    assert "grep" not in script
