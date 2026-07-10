#!/usr/bin/env python3
"""Write the temporary version module used while packaging a release."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


_VERSION_PATTERN = re.compile(r"^\d+(?:\.\d+){1,3}$")
_ROOT = Path(__file__).resolve().parents[1]
_OUTPUT = _ROOT / "src" / "winwhisper" / "_build_version.py"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    args = parser.parse_args()

    if not _VERSION_PATTERN.fullmatch(args.version):
        parser.error("version must contain two to four numeric components")

    _OUTPUT.write_text(
        '"""Generated build version. Do not commit this value."""\n\n'
        f'BUILD_VERSION: str | None = "{args.version}"\n',
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
