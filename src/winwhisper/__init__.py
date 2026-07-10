from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import tomllib

from ._build_version import BUILD_VERSION
from .branding import PACKAGE_DISTRIBUTION


def _version_from_metadata() -> str:
    if BUILD_VERSION:
        return BUILD_VERSION

    try:
        return version(PACKAGE_DISTRIBUTION)
    except PackageNotFoundError:
        pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
        try:
            data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
            return str(data["project"]["version"])
        except Exception:
            return "0+unknown"


__version__ = _version_from_metadata()
