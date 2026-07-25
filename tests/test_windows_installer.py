"""Guards on installer/Speech.iss.

The installer script is only exercised by the release build, so a mistake here
surfaces as a broken release rather than a failing test. These checks cover the
invariants that would be expensive to discover that late.
"""
import re
from pathlib import Path

import pytest

ISS_PATH = Path(__file__).resolve().parents[1] / "installer" / "Speech.iss"
GUID = r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"


@pytest.fixture(scope="module")
def script() -> str:
    return ISS_PATH.read_text(encoding="utf-8")


def test_uninstall_key_guid_matches_appid(script):
    """Inno derives the uninstall key from AppId, so the two must agree.

    SetupSetting("AppId") cannot be used in [Code] because it yields the
    directive text including the brace that escapes a literal '{', so the GUID is
    written out twice. This is the check that keeps the copies in step.
    """
    app_id = re.search(rf"AppId=\{{+({GUID})\}}", script)
    uninstall_key = re.search(rf"Uninstall\\\'\s*\+\s*\'\{{({GUID})\}}_is1", script)

    assert app_id, "AppId GUID not found in [Setup]"
    assert uninstall_key, "uninstall key GUID not found in [Code]"
    assert app_id.group(1).lower() == uninstall_key.group(1).lower()


def test_previous_internal_directory_is_deleted_before_install(script):
    """Without this, updates only ever overlaid the previous install."""
    assert "[InstallDelete]" in script
    assert re.search(
        r"Type:\s*filesandordirs;\s*Name:\s*\"\{app\}\\_internal\"", script
    )


def test_previous_version_is_uninstalled_first(script):
    assert "function PrepareToInstall" in script
    assert "/VERYSILENT" in script
    # The uninstaller relaunches itself from a temp copy, so Exec can return
    # before removal finishes; the script has to wait for the old exe to go.
    assert "FileExists(PreviousExe)" in script


def test_a_failed_uninstall_does_not_abort_the_update(script):
    """PrepareToInstall aborts setup if it returns a non-empty string.

    Aborting is the worst outcome: the updater has already closed Speech, so the
    user would be left with nothing running. Every exit path must leave Result
    empty and fall through to [InstallDelete].
    """
    body = script[script.index("function PrepareToInstall") :]
    assignments = re.findall(r"Result\s*:=\s*([^;]+);", body)

    assert assignments, "PrepareToInstall never assigns Result"
    assert all(value.strip() == "''" for value in assignments), assignments


def test_uninstall_never_deletes_user_settings(script):
    """Every update now runs the old uninstaller, so this became load-bearing.

    An [UninstallDelete] entry covering the app data directory would silently
    wipe settings, hotkeys, and custom vocabulary on every single update.
    """
    assert "[UninstallDelete]" not in script


def test_install_stays_per_user(script):
    # A machine-wide install would need elevation the updater cannot supply.
    assert "PrivilegesRequired=lowest" in script
    assert "DefaultDirName={localappdata}\\Programs\\{#MyAppName}" in script
