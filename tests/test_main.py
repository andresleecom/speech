import builtins
import errno
import os
import sys

import pytest

import winwhisper
import winwhisper.main as main_module
from winwhisper import __version__
from winwhisper.main import _finish_cli, _is_writable_regular_file, main


@pytest.fixture
def reset_posix_single_instance_lock():
    handle = main_module._single_instance_lock_handle
    if handle is not None:
        handle.close()
    main_module._single_instance_lock_handle = None

    yield

    handle = main_module._single_instance_lock_handle
    if handle is not None:
        handle.close()
    main_module._single_instance_lock_handle = None


def test_version_flag_prints_package_version(capsys):
    assert main(["--version"]) == 0

    assert capsys.readouterr().out.strip() == __version__


def test_packaged_build_version_overrides_installed_metadata(monkeypatch):
    monkeypatch.setattr(winwhisper, "BUILD_VERSION", "0.1.12.42")

    assert winwhisper._version_from_metadata() == "0.1.12.42"


def test_finish_cli_returns_in_python_process(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)

    assert _finish_cli(0) == 0


def test_finish_cli_force_exits_in_frozen_process(monkeypatch):
    calls = []
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    def fake_exit(exit_code):
        calls.append(exit_code)
        raise SystemExit(exit_code)

    monkeypatch.setattr(main_module.os, "_exit", fake_exit)

    with pytest.raises(SystemExit) as exc_info:
        _finish_cli(7)

    assert exc_info.value.code == 7
    assert calls == [7]


def test_device_namespace_path_is_not_a_regular_file():
    assert _is_writable_regular_file("\\\\.\\nllMonFltProxy\\FFFFC6813FCC6E10") is False


def test_missing_path_is_not_a_regular_file(tmp_path):
    assert _is_writable_regular_file(str(tmp_path / "absent.log")) is False


def test_writable_file_is_accepted(tmp_path):
    target = tmp_path / "keys.log"
    target.write_text("", encoding="utf-8")

    assert _is_writable_regular_file(str(target)) is True


def test_sslkeylogfile_device_path_is_stripped(monkeypatch, caplog):
    import logging

    monkeypatch.setenv("SSLKEYLOGFILE", r"\\.\nllMonFltProxy\TEST")
    logger = logging.getLogger("test-sslkeylog")
    with caplog.at_level(logging.WARNING):
        main_module._drop_invalid_sslkeylogfile(logger)

    assert "SSLKEYLOGFILE" not in os.environ


def test_open_path_uses_platform_opener(monkeypatch, tmp_path):
    import sys

    import winwhisper.main as main_module

    calls = []

    class FakePopen:
        def __init__(self, args, **kwargs):
            calls.append(args)

    import subprocess

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    target = tmp_path / "settings.json"

    monkeypatch.setattr(sys, "platform", "darwin")
    main_module._open_path(target)
    assert calls[-1] == ["open", str(target)]

    monkeypatch.setattr(sys, "platform", "linux")
    main_module._open_path(target)
    assert calls[-1] == ["xdg-open", str(target)]


@pytest.mark.skipif(os.name == "nt", reason="fcntl is unavailable on Windows")
def test_posix_single_instance_first_acquisition(
    monkeypatch, tmp_path, reset_posix_single_instance_lock
):
    monkeypatch.setattr(main_module, "app_data_dir", lambda: tmp_path)

    assert main_module._acquire_single_instance() is True

    handle = main_module._single_instance_lock_handle
    assert handle is not None
    assert not handle.closed
    assert (tmp_path / main_module._SINGLE_INSTANCE_LOCK_FILE_NAME).is_file()


@pytest.mark.skipif(os.name == "nt", reason="fcntl is unavailable on Windows")
def test_posix_single_instance_competing_acquisition(
    monkeypatch, tmp_path, reset_posix_single_instance_lock
):
    import fcntl

    lock_path = tmp_path / main_module._SINGLE_INSTANCE_LOCK_FILE_NAME
    lock_path.touch()
    with lock_path.open("a") as owner_handle:
        fcntl.flock(owner_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        monkeypatch.setattr(main_module, "app_data_dir", lambda: tmp_path)

        assert main_module._acquire_single_instance() is False
        assert main_module._single_instance_lock_handle is None


@pytest.mark.skipif(os.name == "nt", reason="fcntl is unavailable on Windows")
def test_posix_single_instance_release_and_reacquisition(
    monkeypatch, tmp_path, reset_posix_single_instance_lock
):
    monkeypatch.setattr(main_module, "app_data_dir", lambda: tmp_path)

    assert main_module._acquire_single_instance() is True
    first_handle = main_module._single_instance_lock_handle
    assert first_handle is not None
    first_handle.close()
    main_module._single_instance_lock_handle = None

    assert (tmp_path / main_module._SINGLE_INSTANCE_LOCK_FILE_NAME).exists()
    assert main_module._acquire_single_instance() is True
    assert main_module._single_instance_lock_handle is not first_handle


@pytest.mark.skipif(os.name == "nt", reason="fcntl is unavailable on Windows")
@pytest.mark.parametrize("error_errno", [errno.EACCES, errno.EAGAIN])
def test_posix_single_instance_equivalent_contention_errors(
    monkeypatch, tmp_path, reset_posix_single_instance_lock, error_errno
):
    import fcntl

    monkeypatch.setattr(main_module, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        fcntl,
        "flock",
        lambda *args: (_ for _ in ()).throw(OSError(error_errno, "contended")),
    )

    assert main_module._acquire_single_instance() is False
    assert main_module._single_instance_lock_handle is None


@pytest.mark.skipif(os.name == "nt", reason="fcntl is unavailable on Windows")
@pytest.mark.parametrize("failure_stage", ["directory", "open", "import", "lock"])
def test_posix_single_instance_setup_errors_fail_open(
    monkeypatch, tmp_path, reset_posix_single_instance_lock, failure_stage
):
    import fcntl

    monkeypatch.setattr(main_module, "app_data_dir", lambda: tmp_path)

    if failure_stage == "directory":
        monkeypatch.setattr(
            main_module,
            "app_data_dir",
            lambda: (_ for _ in ()).throw(OSError("directory failed")),
        )
    elif failure_stage == "open":
        monkeypatch.setattr(
            type(tmp_path),
            "open",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("open failed")),
        )
    elif failure_stage == "import":
        real_import = builtins.__import__

        def fail_fcntl_import(name, *args, **kwargs):
            if name == "fcntl":
                raise ImportError("fcntl failed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fail_fcntl_import)
    else:
        monkeypatch.setattr(
            fcntl,
            "flock",
            lambda *args: (_ for _ in ()).throw(OSError("lock failed")),
        )

    assert main_module._acquire_single_instance() is True
    assert main_module._single_instance_lock_handle is None
