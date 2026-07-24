import subprocess
import sys

import pytest

from winwhisper import updater
from winwhisper.updater import (
    ReleaseAsset,
    UpdateInfo,
    current_app_executable,
    launch_installer,
    prune_update_downloads,
)


def _captured_command(monkeypatch, **kwargs):
    captured = {}

    def fake_popen(args, **popen_kwargs):
        captured["args"] = args
        return object()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr("os.name", "nt")
    launch_installer(**kwargs)
    return " ".join(str(part) for part in captured["args"])


def test_installer_relaunches_speech_after_a_silent_install(monkeypatch, tmp_path):
    installer = tmp_path / "Speech-Setup-1.2.3.exe"
    installer.write_bytes(b"")
    app = tmp_path / "Speech.exe"
    app.write_bytes(b"")

    command = _captured_command(
        monkeypatch, installer_path=installer, wait_for_pid=4321, relaunch_path=app
    )

    assert "Wait-Process -Id 4321" in command
    assert "/SILENT" in command and "/CURRENTUSER" in command
    # -Wait matters: without it Speech would restart while the installer is
    # still replacing the binaries it is about to run.
    assert "-Wait; Start-Process -FilePath" in command
    assert "Speech.exe" in command.split("-Wait;")[1]


def test_no_relaunch_is_requested_when_running_from_source(monkeypatch, tmp_path):
    installer = tmp_path / "Speech-Setup-1.2.3.exe"
    installer.write_bytes(b"")

    command = _captured_command(
        monkeypatch, installer_path=installer, wait_for_pid=99, relaunch_path=None
    )

    assert "Wait-Process -Id 99" in command
    assert "-Wait;" not in command


def test_current_app_executable_is_none_unless_frozen(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert current_app_executable() is None

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\Speech\Speech.exe")
    assert str(current_app_executable()).endswith("Speech.exe")


def test_pruning_removes_old_installers_and_reports_bytes_freed(tmp_path):
    old = tmp_path / "Speech-Setup-0.1.12.20.exe"
    old.write_bytes(b"x" * 2048)
    (tmp_path / "Speech-Setup-0.1.12.20.exe.sha256").write_bytes(b"y" * 64)
    keep = tmp_path / "Speech-Setup-0.1.13.28.exe"
    keep.write_bytes(b"z" * 512)

    freed = prune_update_downloads(tmp_path, keep=(keep.name,))

    assert freed == 2048 + 64
    assert not old.exists()
    assert keep.exists()


def test_pruning_clears_abandoned_partial_downloads(tmp_path):
    partial = tmp_path / "Speech-Setup-0.1.13.28.exe.partial"
    partial.write_bytes(b"x" * 128)

    prune_update_downloads(tmp_path)

    assert not partial.exists()


def test_pruning_never_touches_unrelated_files(tmp_path):
    stranger = tmp_path / "important-notes.txt"
    stranger.write_bytes(b"keep me")
    model = tmp_path / "model.bin"
    model.write_bytes(b"keep me too")

    prune_update_downloads(tmp_path)

    assert stranger.exists()
    assert model.exists()


def test_pruning_is_case_insensitive_about_the_kept_name(tmp_path):
    keep = tmp_path / "Speech-Setup-1.0.exe"
    keep.write_bytes(b"x")

    prune_update_downloads(tmp_path, keep=("speech-setup-1.0.EXE",))

    assert keep.exists()


def test_pruning_survives_a_missing_directory(tmp_path):
    assert prune_update_downloads(tmp_path / "nope") == 0


def test_download_prunes_before_writing_the_new_installer(monkeypatch, tmp_path):
    # Reclaiming space first matters on a nearly full disk: otherwise the old
    # installers and the new one have to coexist.
    stale = tmp_path / "Speech-Setup-0.0.1.exe"
    stale.write_bytes(b"x" * 4096)
    order = []

    def fake_download(url, dest, max_bytes):
        order.append(("download", stale.exists()))
        dest.write_bytes(b"new")

    monkeypatch.setattr(updater, "_download_to_path", fake_download)
    monkeypatch.setattr(updater, "verify_sha256", lambda target, checksum: True)

    update = UpdateInfo(
        version="1.0.0",
        release_url="https://github.com/andresleecom/speech/releases/tag/v1.0.0",
        installer=ReleaseAsset(
            name="Speech-Setup-1.0.0.exe",
            download_url="https://github.com/andresleecom/speech/x.exe",
        ),
        checksum=ReleaseAsset(
            name="Speech-Setup-1.0.0.exe.sha256",
            download_url="https://github.com/andresleecom/speech/x.exe.sha256",
        ),
    )

    updater.download_update(update, target_dir=tmp_path)

    assert not stale.exists()
    assert order and order[0] == ("download", False)
    assert (tmp_path / "Speech-Setup-1.0.0.exe").exists()
