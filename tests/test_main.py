from winwhisper.main import _is_writable_regular_file


def test_device_namespace_path_is_not_a_regular_file():
    assert _is_writable_regular_file("\\\\.\\nllMonFltProxy\\FFFFC6813FCC6E10") is False


def test_missing_path_is_not_a_regular_file(tmp_path):
    assert _is_writable_regular_file(str(tmp_path / "absent.log")) is False


def test_writable_file_is_accepted(tmp_path):
    target = tmp_path / "keys.log"
    target.write_text("", encoding="utf-8")

    assert _is_writable_regular_file(str(target)) is True
