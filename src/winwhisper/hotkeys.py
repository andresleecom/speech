from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from typing import Any

from .logger import get_logger

_ACTIONS = {
    "toggle_recording": "toggle",
    "force_english": "force_en",
    "force_spanish": "force_es",
}


class HotkeyManager:
    def __init__(
        self,
        hotkey_map: Mapping[str, str],
        on_hotkey: Callable[[str], None],
    ) -> None:
        self._hotkey_map = dict(hotkey_map)
        self._on_hotkey = on_hotkey
        self._listener: Any | None = None
        self._logger = get_logger(__name__)

    def start(self) -> None:
        if self._listener is not None:
            return

        from pynput.keyboard import GlobalHotKeys

        bindings = {
            combo: self._handler_for(action)
            for setting_key, action in _ACTIONS.items()
            if (combo := self._hotkey_map.get(setting_key))
        }
        self._listener = GlobalHotKeys(bindings)
        self._listener.start()

    def stop(self) -> None:
        listener = self._listener
        if listener is None:
            return

        listener.stop()
        self._listener = None

    def _handler_for(self, action: str) -> Callable[[], None]:
        def handler() -> None:
            thread = threading.Thread(
                target=self._dispatch,
                args=(action,),
                daemon=True,
            )
            thread.start()

        return handler

    def _dispatch(self, action: str) -> None:
        try:
            self._on_hotkey(action)
        except Exception:
            self._logger.exception("Hotkey callback failed for action %s.", action)
