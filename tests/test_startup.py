"""Tests for Windows start-at-login registry helpers."""

from __future__ import annotations

import types

import pytest

import winwhisper.startup as startup_module


class FakeWinreg:
    HKEY_CURRENT_USER = object()
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.deleted: list[str] = []
        self.set_calls: list[tuple[str, str]] = []

    def OpenKey(self, hive, subkey, reserved=0, access=0):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise OSError(2, "not found")
        return self.values[name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, value_type, value):
        self.values[name] = value
        self.set_calls.append((name, value))

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise OSError(2, "not found")
        del self.values[name]
        self.deleted.append(name)


@pytest.fixture
def fake_winreg(monkeypatch):
    fake = FakeWinreg()
    module = types.ModuleType("winreg")
    module.HKEY_CURRENT_USER = fake.HKEY_CURRENT_USER
    module.KEY_SET_VALUE = fake.KEY_SET_VALUE
    module.REG_SZ = fake.REG_SZ
    module.OpenKey = fake.OpenKey
    module.QueryValueEx = fake.QueryValueEx
    module.SetValueEx = fake.SetValueEx
    module.DeleteValue = fake.DeleteValue
    monkeypatch.setitem(__import__("sys").modules, "winreg", module)
    monkeypatch.setattr(startup_module.sys, "platform", "win32")
    return fake


def test_is_enabled_false_on_non_windows(monkeypatch):
    monkeypatch.setattr(startup_module.sys, "platform", "darwin")
    assert startup_module.is_enabled() is False
    assert startup_module.enable(r"C:\Speech\Speech.exe") is False
    assert startup_module.disable() is False


def test_installed_executable_none_when_not_frozen(monkeypatch):
    monkeypatch.setattr(startup_module.sys, "platform", "win32")
    monkeypatch.delattr(startup_module.sys, "frozen", raising=False)
    assert startup_module.installed_executable() is None


def test_installed_executable_none_on_non_windows(monkeypatch):
    monkeypatch.setattr(startup_module.sys, "platform", "darwin")
    monkeypatch.setattr(startup_module.sys, "frozen", True, raising=False)
    assert startup_module.installed_executable() is None


def test_installed_executable_returns_sys_executable_when_frozen(monkeypatch):
    monkeypatch.setattr(startup_module.sys, "platform", "win32")
    monkeypatch.setattr(startup_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        startup_module.sys, "executable", r"C:\Programs\Speech\Speech.exe"
    )
    assert startup_module.installed_executable() == r"C:\Programs\Speech\Speech.exe"


def test_enable_writes_quoted_path(fake_winreg):
    assert startup_module.is_enabled() is False
    assert startup_module.enable(r"C:\Programs\Speech\Speech.exe") is True
    assert startup_module.is_enabled() is True
    assert fake_winreg.set_calls == [
        ("Speech", r'"C:\Programs\Speech\Speech.exe"')
    ]


def test_disable_removes_value(fake_winreg):
    fake_winreg.values["Speech"] = r'"C:\Speech\Speech.exe"'
    assert startup_module.disable() is True
    assert startup_module.is_enabled() is False
    assert fake_winreg.deleted == ["Speech"]
