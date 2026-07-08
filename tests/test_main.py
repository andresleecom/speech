import sys

import pytest

import winwhisper.main as main_module
from winwhisper import __version__
from winwhisper.main import _finish_cli, _is_writable_regular_file, main


def test_version_flag_prints_package_version(capsys):
    assert main(["--version"]) == 0

    assert capsys.readouterr().out.strip() == __version__


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
