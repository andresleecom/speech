import hashlib
import pytest

from winwhisper.updater import (
    UPDATE_CHECK_INTERVAL_SECONDS,
    ReleaseAsset,
    UpdateInfo,
    download_update,
    is_allowed_download_url,
    is_newer_version,
    parse_latest_release,
    safe_asset_filename,
    select_windows_assets,
    should_check_for_updates,
    verify_sha256,
)


def test_is_newer_version_accepts_v_prefix_and_semver_parts():
    assert is_newer_version("v0.1.1", "0.1.0") is True
    assert is_newer_version("0.1.0", "0.1.0") is False
    assert is_newer_version("0.1.0", "0.1.1") is False


def test_should_check_for_updates_respects_daily_interval():
    now = 1_800_000_000.0

    assert should_check_for_updates(True, None, now) is True
    assert should_check_for_updates(False, None, now) is False
    assert should_check_for_updates(True, now - 60, now) is False
    assert (
        should_check_for_updates(
            True,
            now - UPDATE_CHECK_INTERVAL_SECONDS,
            now,
        )
        is True
    )


def test_select_windows_assets_prefers_installer_and_matching_sha():
    installer = ReleaseAsset(
        name="Speech-Setup-0.2.0.exe",
        download_url="https://example.com/setup.exe",
    )
    checksum = ReleaseAsset(
        name="Speech-Setup-0.2.0.exe.sha256",
        download_url="https://example.com/setup.exe.sha256",
    )
    ignored = ReleaseAsset(
        name="Speech-portable.zip",
        download_url="https://example.com/portable.zip",
    )

    assert select_windows_assets([ignored, checksum, installer]) == (
        installer,
        checksum,
    )


def test_parse_latest_release_returns_update_info_for_new_windows_release():
    payload = {
        "tag_name": "v0.2.0",
        "html_url": "https://github.com/andresleecom/speech/releases/tag/v0.2.0",
        "assets": [
            {
                "name": "Speech-Setup-0.2.0.exe",
                "browser_download_url": "https://example.com/setup.exe",
            },
            {
                "name": "Speech-Setup-0.2.0.exe.sha256",
                "browser_download_url": "https://example.com/setup.exe.sha256",
            },
        ],
    }

    update = parse_latest_release(payload, current_version="0.1.0")

    assert update is not None
    assert update.version == "0.2.0"
    assert update.installer.name == "Speech-Setup-0.2.0.exe"


def test_parse_latest_release_ignores_current_version():
    payload = {
        "tag_name": "v0.1.0",
        "html_url": "https://github.com/andresleecom/speech/releases/tag/v0.1.0",
        "assets": [],
    }

    assert parse_latest_release(payload, current_version="0.1.0") is None


def test_parse_latest_release_requires_checksum_asset():
    payload = {
        "tag_name": "v0.2.0",
        "html_url": "https://github.com/andresleecom/speech/releases/tag/v0.2.0",
        "assets": [
            {
                "name": "Speech-Setup-0.2.0.exe",
                "browser_download_url": "https://example.com/setup.exe",
            },
        ],
    }

    assert parse_latest_release(payload, current_version="0.1.0") is None


def test_verify_sha256_reads_hex_digest(tmp_path):
    target = tmp_path / "installer.exe"
    target.write_bytes(b"installer")
    checksum = tmp_path / "installer.exe.sha256"
    digest = hashlib.sha256(b"installer").hexdigest()
    checksum.write_text(
        f"{digest}  installer.exe\n",
        encoding="utf-8",
    )

    assert verify_sha256(target, checksum) is True


def test_verify_sha256_rejects_mismatch(tmp_path):
    target = tmp_path / "installer.exe"
    target.write_bytes(b"installer")
    checksum = tmp_path / "installer.exe.sha256"
    checksum.write_text("0" * 64, encoding="utf-8")

    assert verify_sha256(target, checksum) is False


def test_download_update_requires_checksum(tmp_path):
    update = UpdateInfo(
        version="0.2.0",
        release_url="https://example.com/release",
        installer=ReleaseAsset(
            name="Speech-Setup-0.2.0.exe",
            download_url="https://example.com/setup.exe",
        ),
        checksum=None,
    )

    with pytest.raises(ValueError, match="checksum"):
        download_update(update, tmp_path)


def test_safe_asset_filename_rejects_path_traversal():
    assert safe_asset_filename("Speech-Setup-0.2.0.exe") == "Speech-Setup-0.2.0.exe"
    with pytest.raises(ValueError):
        safe_asset_filename("..\\evil.exe")
    with pytest.raises(ValueError):
        safe_asset_filename("subdir/installer.exe")


def test_is_allowed_download_url_requires_https_github_hosts():
    assert is_allowed_download_url(
        "https://github.com/andresleecom/speech/releases/download/v1/x.exe"
    )
    assert is_allowed_download_url(
        "https://objects.githubusercontent.com/github-production-release-asset/1"
    )
    assert not is_allowed_download_url("http://github.com/andresleecom/speech/x.exe")
    assert not is_allowed_download_url("https://evil.example/setup.exe")


def test_download_update_rejects_disallowed_url(tmp_path):
    update = UpdateInfo(
        version="0.2.0",
        release_url="https://github.com/andresleecom/speech/releases/tag/v0.2.0",
        installer=ReleaseAsset(
            name="Speech-Setup-0.2.0.exe",
            download_url="https://evil.example/setup.exe",
        ),
        checksum=ReleaseAsset(
            name="Speech-Setup-0.2.0.exe.sha256",
            download_url="https://evil.example/setup.exe.sha256",
        ),
    )

    with pytest.raises(ValueError, match="allowlisted"):
        download_update(update, tmp_path)
