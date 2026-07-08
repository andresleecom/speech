from winwhisper.logger import get_logger


def test_main_module_logger_stays_in_package_hierarchy(monkeypatch, tmp_path):
    monkeypatch.setenv("WINWHISPER_APPDATA_DIR", str(tmp_path))

    logger = get_logger("__main__")

    assert logger.name == "winwhisper.main"
