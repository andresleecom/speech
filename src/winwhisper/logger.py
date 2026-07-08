from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from .config import app_data_dir

_CONFIGURED = False


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger.

    Privacy warning: never log transcripts, raw audio, or audio-derived content.
    """
    _setup_logging()
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    return logger


def _setup_logging() -> None:
    global _CONFIGURED

    if _CONFIGURED:
        return

    log_dir = app_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )

    file_handler = RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)

    package_logger = logging.getLogger("winwhisper")
    package_logger.setLevel(logging.INFO)
    package_logger.propagate = False
    package_logger.handlers.clear()
    package_logger.addHandler(file_handler)
    package_logger.addHandler(stream_handler)

    _CONFIGURED = True
