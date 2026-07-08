from __future__ import annotations

import hashlib
import json
import re
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .branding import APP_NAME, GITHUB_REPOSITORY
from .config import app_data_dir

LATEST_RELEASE_API_URL = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
UPDATE_CHECK_INTERVAL_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    download_url: str


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    release_url: str
    installer: ReleaseAsset
    checksum: ReleaseAsset | None = None


def normalized_version(version: str) -> str:
    return version.strip().removeprefix("v").removeprefix("V")


def version_tuple(version: str) -> tuple[int, ...]:
    normalized = normalized_version(version)
    match = re.match(r"^(\d+(?:\.\d+){0,3})", normalized)
    if not match:
        return (0,)
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer_version(latest: str, current: str) -> bool:
    latest_parts = version_tuple(latest)
    current_parts = version_tuple(current)
    length = max(len(latest_parts), len(current_parts))
    latest_parts += (0,) * (length - len(latest_parts))
    current_parts += (0,) * (length - len(current_parts))
    return latest_parts > current_parts


def should_check_for_updates(
    enabled: bool,
    last_checked_at: float | None,
    now: float,
) -> bool:
    if not enabled:
        return False
    if last_checked_at is None:
        return True
    return now - last_checked_at >= UPDATE_CHECK_INTERVAL_SECONDS


def parse_latest_release(
    payload: dict[str, Any],
    current_version: str,
) -> UpdateInfo | None:
    tag_name = str(payload.get("tag_name") or "")
    if not tag_name or not is_newer_version(tag_name, current_version):
        return None

    assets = [
        ReleaseAsset(
            name=str(asset.get("name") or ""),
            download_url=str(asset.get("browser_download_url") or ""),
        )
        for asset in payload.get("assets", [])
        if isinstance(asset, dict)
    ]
    installer, checksum = select_windows_assets(assets)
    if installer is None or checksum is None:
        return None

    return UpdateInfo(
        version=normalized_version(tag_name),
        release_url=str(payload.get("html_url") or ""),
        installer=installer,
        checksum=checksum,
    )


def select_windows_assets(
    assets: list[ReleaseAsset],
) -> tuple[ReleaseAsset | None, ReleaseAsset | None]:
    installer = next(
        (
            asset
            for asset in assets
            if asset.name.lower().endswith(".exe")
            and "setup" in asset.name.lower()
            and asset.download_url
        ),
        None,
    )
    if installer is None:
        return None, None

    checksum = next(
        (
            asset
            for asset in assets
            if asset.name.lower() in {f"{installer.name.lower()}.sha256", "sha256sums.txt"}
            and asset.download_url
        ),
        None,
    )
    return installer, checksum


def fetch_latest_release(
    current_version: str,
    api_url: str = LATEST_RELEASE_API_URL,
    timeout: float = 8.0,
) -> UpdateInfo | None:
    request = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": APP_NAME,
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        return None
    return parse_latest_release(payload, current_version)


def updates_dir() -> Path:
    return app_data_dir() / "updates"


def download_update(
    update: UpdateInfo,
    target_dir: Path | None = None,
) -> tuple[Path, Path | None]:
    if update.checksum is None:
        raise ValueError("Update checksum asset is required.")

    target_dir = target_dir or updates_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    installer_path = target_dir / update.installer.name
    urllib.request.urlretrieve(update.installer.download_url, installer_path)

    checksum_path = target_dir / update.checksum.name
    urllib.request.urlretrieve(update.checksum.download_url, checksum_path)
    if not verify_sha256(installer_path, checksum_path):
        installer_path.unlink(missing_ok=True)
        raise ValueError("Downloaded installer checksum did not match.")

    return installer_path, checksum_path


def verify_sha256(target: Path, checksum_file: Path) -> bool:
    expected = _read_expected_sha256(checksum_file, target.name)
    if expected is None:
        return False
    return sha256_file(target).lower() == expected.lower()


def sha256_file(target: Path) -> str:
    digest = hashlib.sha256()
    with target.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def launch_installer(installer_path: Path) -> None:
    subprocess.Popen(
        [
            str(installer_path),
            "/SILENT",
            "/NORESTART",
            "/CURRENTUSER",
        ],
        close_fds=True,
    )


def _read_expected_sha256(checksum_file: Path, target_name: str) -> str | None:
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        digest = parts[0]
        if not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
            continue
        if len(parts) == 1 or parts[-1].lstrip("*") == target_name:
            return digest
    return None
