from __future__ import annotations

from pathlib import Path
from typing import Any

APP_NAME = "Speech"
LEGACY_APP_NAME = "WinWhisperDictate"
GITHUB_REPOSITORY = "andresleecom/speech"
PACKAGE_DISTRIBUTION = "speech"

# The app mark: the circle the tray draws while idle, reused as the window icon
# so the settings dialogs do not fall back to Tk's feather.
IDLE_ICON_COLOR = (128, 128, 128, 255)
_ICON_OUTLINE_COLOR = (255, 255, 255, 255)

_ASSET_NAME = "app-icon-256.png"


def _asset_icon_path() -> Path | None:
    """Return the packaged PNG path when the file is present on disk."""
    candidate = Path(__file__).resolve().parent / "assets" / _ASSET_NAME
    if candidate.is_file():
        return candidate
    return None


def app_icon_image(
    size: int = 64,
    *,
    color: tuple[int, int, int, int] | None = None,
) -> Any:
    """Return the app mark as a Pillow image.

    The tray passes its per-status color and always gets the drawn status disc.
    Everything else prefers the packaged PNG when present, then falls back to
    the idle circle.
    """
    from PIL import Image, ImageDraw

    if color is None:
        asset = _asset_icon_path()
        if asset is not None:
            with Image.open(asset) as opened:
                image = opened.convert("RGBA")
            if image.size != (size, size):
                image = image.resize((size, size), Image.Resampling.LANCZOS)
            return image

    fill = color if color is not None else IDLE_ICON_COLOR
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    inset = size / 8
    box = (inset, inset, size - inset, size - inset)
    draw.ellipse(box, fill=fill)
    draw.ellipse(box, outline=_ICON_OUTLINE_COLOR, width=max(1, round(size * 3 / 64)))
    return image


def apply_tk_app_icon(window: Any) -> None:
    """Give a Tk window the app mark instead of Tk's default feather.

    Best effort: a Pillow build without ImageTk, or a Tk that refuses the
    image, must not take the settings dialog down with it.
    """
    try:
        from PIL import ImageTk

        photo = ImageTk.PhotoImage(app_icon_image())
        window.iconphoto(True, photo)
        # Tk keeps no reference of its own, so the image has to outlive this
        # call or the icon disappears when it is garbage collected.
        window._speech_app_icon = photo
    except Exception:
        pass
