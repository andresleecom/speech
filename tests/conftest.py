"""Session-wide isolation so pytest never touches the real app data dir."""

from __future__ import annotations

import logging
import os
import tempfile

import pytest

# Must run at import time: collection imports test modules that pull in
# winwhisper, and logger._setup_logging sticks the first app_data_dir() it sees.
_BOOTSTRAP_APPDATA = tempfile.mkdtemp(prefix="winwhisper-pytest-appdata-")
os.environ["WINWHISPER_APPDATA_DIR"] = _BOOTSTRAP_APPDATA


def pytest_configure(config: pytest.Config) -> None:
    if not os.environ.get("WINWHISPER_APPDATA_DIR"):
        os.environ["WINWHISPER_APPDATA_DIR"] = tempfile.mkdtemp(
            prefix="winwhisper-pytest-appdata-"
        )


def _reset_winwhisper_logging() -> None:
    """Drop sticky handlers so a new WINWHISPER_APPDATA_DIR can take effect."""
    try:
        from winwhisper import logger as winwhisper_logger
    except ImportError:
        return

    package_logger = logging.getLogger("winwhisper")
    for handler in list(package_logger.handlers):
        try:
            handler.close()
        except Exception:
            pass
    package_logger.handlers.clear()
    winwhisper_logger._CONFIGURED = False


@pytest.fixture(scope="session", autouse=True)
def _isolate_appdata_dir(tmp_path_factory: pytest.TempPathFactory):
    appdata = tmp_path_factory.mktemp("appdata")
    os.environ["WINWHISPER_APPDATA_DIR"] = str(appdata)
    _reset_winwhisper_logging()
    yield
