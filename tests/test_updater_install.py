import json
import os
import subprocess
import sys
import time

import pytest

from winwhisper import updater
from winwhisper.updater import (
    ReleaseAsset,
    UpdateInfo,
    current_app_executable,
    launch_installer,
    powershell_single_quoted,
    prune_update_downloads,
    windows_hidden_process_creationflags,
)


def _captured_popen(monkeypatch, **kwargs):
    captured = {}

    def fake_popen(args, **popen_kwargs):
        captured["args"] = args
        captured["kwargs"] = popen_kwargs
        return object()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr("os.name", "nt")
    returned = launch_installer(**kwargs)
    captured["command"] = " ".join(str(part) for part in captured["args"])
    captured["returned"] = returned
    return captured


def test_installer_relaunches_speech_after_a_silent_install(monkeypatch, tmp_path):
    installer = tmp_path / "Speech-Setup-1.2.3.exe"
    installer.write_bytes(b"")
    app = tmp_path / "Speech.exe"
    app.write_bytes(b"")

    captured = _captured_popen(
        monkeypatch, installer_path=installer, wait_for_pid=4321, relaunch_path=app
    )
    command = captured["command"]
    creationflags = captured["kwargs"].get("creationflags", 0)

    assert "Wait-Process -Id 4321" in command
    assert "-Timeout" in command
    assert "handoff.log" in command
    assert "-PassThru" in command
    assert "/SILENT" in command and "/CURRENTUSER" in command
    assert "/SUPPRESSMSGBOXES" in command
    install_log = str((installer.parent / "install.log").resolve())
    assert f"'/LOG=\"{install_log}\"'" in command
    assert "Speech.exe" in command
    assert "relaunching" in command
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        assert creationflags & subprocess.CREATE_NO_WINDOW
    if hasattr(subprocess, "DETACHED_PROCESS"):
        assert not (creationflags & subprocess.DETACHED_PROCESS)
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        assert creationflags & subprocess.CREATE_NEW_PROCESS_GROUP
    assert "Wait-Process -Id 4321" in captured["returned"]


def test_installer_log_argument_uses_powershell_single_quotes(monkeypatch, tmp_path):
    # Start-Process joins -ArgumentList with spaces; PS single-quoted elements
    # plus embedded "..." around the log path keep a spaced path as one token.
    installer = tmp_path / "Speech-Setup-1.2.3.exe"
    installer.write_bytes(b"")

    captured = _captured_popen(
        monkeypatch, installer_path=installer, wait_for_pid=7, relaunch_path=None
    )
    command = captured["command"]
    install_log = str((installer.parent / "install.log").resolve())

    assert "'/LOG=\"" in command
    assert install_log in command
    assert f"'/LOG=\"{install_log}\"'" in command


def test_powershell_single_quoted_doubles_embedded_quotes():
    assert powershell_single_quoted("a'b") == "'a''b'"
    assert powershell_single_quoted(r"C:\Users\O'Brien\log.txt") == (
        r"'C:\Users\O''Brien\log.txt'"
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows Start-Process quoting check")
def test_powershell_argumentlist_quoting_survives_start_process(tmp_path):
    # Prove the helper's quoting keeps a path-with-spaces intact through
    # Start-Process -ArgumentList (the same join that broke /LOG=).
    spaced = tmp_path / "dir with space" / "file.txt"
    spaced.parent.mkdir(parents=True, exist_ok=True)
    out = tmp_path / "stdout.txt"
    quoted_path = f'"{spaced}"'
    argument_list = ",".join(
        powershell_single_quoted(arg)
        for arg in ["/c", "echo", quoted_path]
    )
    command = (
        f"Start-Process -FilePath cmd.exe -ArgumentList {argument_list} "
        f"-Wait -RedirectStandardOutput {json.dumps(str(out))}"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert out.exists()
    assert str(spaced) in out.read_text(encoding="utf-8", errors="replace")


def test_no_relaunch_is_requested_when_running_from_source(monkeypatch, tmp_path):
    installer = tmp_path / "Speech-Setup-1.2.3.exe"
    installer.write_bytes(b"")

    captured = _captured_popen(
        monkeypatch, installer_path=installer, wait_for_pid=99, relaunch_path=None
    )
    command = captured["command"]

    assert "Wait-Process -Id 99" in command
    assert "relaunching" not in command
    # Installer still waits to finish; only the Speech relaunch is omitted.
    assert "-PassThru -Wait" in command


def test_current_app_executable_is_none_unless_frozen(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert current_app_executable() is None

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\Speech\Speech.exe")
    assert str(current_app_executable()).endswith("Speech.exe")


@pytest.mark.skipif(os.name != "nt", reason="Windows-only process creation flags")
def test_windows_hidden_creationflags_run_powershell_command(tmp_path):
    marker = tmp_path / "marker.txt"
    flags = windows_hidden_process_creationflags()
    assert flags & subprocess.CREATE_NO_WINDOW
    if hasattr(subprocess, "DETACHED_PROCESS"):
        assert not (flags & subprocess.DETACHED_PROCESS)

    command = f"'ok' | Out-File -FilePath {json.dumps(str(marker))} -Encoding utf8"
    subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-WindowStyle",
            "Hidden",
            "-Command",
            command,
        ],
        close_fds=True,
        creationflags=flags,
    )

    deadline = time.time() + 20
    while time.time() < deadline:
        if marker.exists() and "ok" in marker.read_text(encoding="utf-8"):
            return
        time.sleep(0.1)
    pytest.fail("marker file was not written within 20 seconds")


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
