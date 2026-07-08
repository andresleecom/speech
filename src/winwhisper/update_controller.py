from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from . import __version__
from .branding import APP_NAME
from .config import Settings, save_settings
from .updater import (
    UpdateInfo,
    download_update,
    fetch_latest_release,
    launch_installer,
    should_check_for_updates,
)


class UpdateCoordinator:
    def __init__(
        self,
        settings: Settings,
        notify: Callable[[str, str], None],
        exit_app: Callable[[], None],
        logger: Any,
    ) -> None:
        self._settings = settings
        self._notify = notify
        self._exit_app = exit_app
        self._logger = logger
        self._lock = threading.Lock()
        self._checking = False

    def maybe_check_for_updates(self) -> None:
        now = time.time()
        if not should_check_for_updates(
            self._settings.check_for_updates,
            self._settings.last_update_check_at,
            now,
        ):
            return

        self._settings.last_update_check_at = now
        save_settings(self._settings)
        self.check_for_updates(manual=False)

    def check_for_updates(self, manual: bool = True) -> None:
        with self._lock:
            if self._checking:
                if manual:
                    self._notify(APP_NAME, "Already checking for updates.")
                return
            self._checking = True

        thread = threading.Thread(
            target=self._check_for_updates_worker,
            args=(manual,),
            name="winwhisper-update-checker",
            daemon=True,
        )
        thread.start()

    def _check_for_updates_worker(self, manual: bool) -> None:
        try:
            update = fetch_latest_release(__version__)
            if update is None:
                if manual:
                    self._notify(APP_NAME, "You are up to date.")
                return

            if not manual:
                self._notify(
                    f"{APP_NAME} update available",
                    f"Version {update.version} is available. Use Check for Updates to install.",
                )
                return

            if not self._confirm_update_install(update):
                return

            self._notify(APP_NAME, f"Downloading version {update.version}.")
            installer_path, _checksum_path = download_update(update)
            self._notify(APP_NAME, "Starting installer.")
            launch_installer(installer_path)
            self._exit_app()
        except Exception as exc:
            self._logger.warning("Update check failed with %s.", exc.__class__.__name__)
            if manual:
                self._notify(APP_NAME, "Update check failed. See log.")
        finally:
            with self._lock:
                self._checking = False

    def _confirm_update_install(self, update: UpdateInfo) -> bool:
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            try:
                return bool(
                    messagebox.askyesno(
                        f"{APP_NAME} update",
                        f"Version {update.version} is available.\n\n"
                        "Download and install it now?",
                        parent=root,
                    )
                )
            finally:
                root.destroy()
        except Exception as exc:
            self._logger.warning(
                "Update confirmation failed with %s; cancelling update.",
                exc.__class__.__name__,
            )
            return False
