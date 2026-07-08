from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .branding import APP_NAME, GITHUB_REPOSITORY
from .config import app_data_dir

LATEST_RELEASE_API_URL = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
UPDATE_CHECK_INTERVAL_SECONDS = 24 * 60 * 60
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024
_ALLOWED_DOWNLOAD_HOSTS = frozenset(
    {
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
)


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
            and _is_safe_asset_name(asset.name)
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
            and _is_safe_asset_name(asset.name)
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


def safe_asset_filename(name: str) -> str:
    """Return a basename-only asset name, rejecting path traversal."""
    if not name or name.strip() != name:
        raise ValueError("Asset name is empty or has surrounding whitespace.")
    if "/" in name or "\\" in name:
        raise ValueError("Asset name must not contain path separators.")
    if name in {".", ".."} or ".." in name:
        raise ValueError("Asset name is not allowed.")
    base = Path(name).name
    if base != name or not base:
        raise ValueError("Asset name is not allowed.")
    return base


def is_allowed_download_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme.lower() != "https":
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if host in _ALLOWED_DOWNLOAD_HOSTS:
        return True
    return host.endswith(".githubusercontent.com")


def download_update(
    update: UpdateInfo,
    target_dir: Path | None = None,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
) -> tuple[Path, Path | None]:
    if update.checksum is None:
        raise ValueError("Update checksum asset is required.")

    installer_name = safe_asset_filename(update.installer.name)
    checksum_name = safe_asset_filename(update.checksum.name)

    if not is_allowed_download_url(update.installer.download_url):
        raise ValueError("Installer download URL is not allowlisted.")
    if not is_allowed_download_url(update.checksum.download_url):
        raise ValueError("Checksum download URL is not allowlisted.")

    target_dir = target_dir or updates_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target_dir = target_dir.resolve()

    installer_path = _resolve_under(target_dir, installer_name)
    checksum_path = _resolve_under(target_dir, checksum_name)

    _download_to_path(update.installer.download_url, installer_path, max_bytes=max_bytes)
    try:
        _download_to_path(update.checksum.download_url, checksum_path, max_bytes=max_bytes)
        if not verify_sha256(installer_path, checksum_path):
            installer_path.unlink(missing_ok=True)
            checksum_path.unlink(missing_ok=True)
            raise ValueError("Downloaded installer checksum did not match.")
    except Exception:
        installer_path.unlink(missing_ok=True)
        checksum_path.unlink(missing_ok=True)
        raise

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


def launch_installer(
    installer_path: Path,
    wait_for_pid: int | None = None,
) -> None:
    """Launch the installer, optionally after the given process exits.

    Waiting for our own PID lets Speech release file locks before Inno Setup
    replaces binaries under the install directory.
    """
    installer = str(installer_path.resolve())
    args = [installer, "/SILENT", "/NORESTART", "/CURRENTUSER"]

    if wait_for_pid is not None and os.name == "nt":
        command = (
            f"Wait-Process -Id {int(wait_for_pid)} -ErrorAction SilentlyContinue; "
            f"Start-Process -FilePath {json.dumps(installer)} "
            f"-ArgumentList '/SILENT','/NORESTART','/CURRENTUSER'"
        )
        creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags |= subprocess.CREATE_NO_WINDOW
        if hasattr(subprocess, "DETACHED_PROCESS"):
            creationflags |= subprocess.DETACHED_PROCESS
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-WindowStyle",
                "Hidden",
                "-Command",
                command,
            ],
            close_fds=True,
            creationflags=creationflags,
        )
        return

    subprocess.Popen(args, close_fds=True)


def _is_safe_asset_name(name: str) -> bool:
    try:
        safe_asset_filename(name)
        return True
    except ValueError:
        return False


def _resolve_under(directory: Path, name: str) -> Path:
    candidate = (directory / name).resolve()
    if directory not in candidate.parents and candidate != directory:
        raise ValueError("Resolved download path escapes the updates directory.")
    if candidate.parent != directory:
        raise ValueError("Resolved download path escapes the updates directory.")
    return candidate


def _download_to_path(url: str, dest: Path, max_bytes: int) -> None:
    partial = dest.with_name(dest.name + ".partial")
    partial.unlink(missing_ok=True)
    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": APP_NAME},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                try:
                    if int(content_length) > max_bytes:
                        raise ValueError("Download exceeded size limit.")
                except ValueError as exc:
                    if "size limit" in str(exc):
                        raise
            written = 0
            with partial.open("wb") as out:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > max_bytes:
                        raise ValueError("Download exceeded size limit.")
                    out.write(chunk)
        os.replace(partial, dest)
    except (OSError, urllib.error.URLError, ValueError):
        partial.unlink(missing_ok=True)
        dest.unlink(missing_ok=True)
        raise
    except Exception:
        partial.unlink(missing_ok=True)
        dest.unlink(missing_ok=True)
        raise


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
