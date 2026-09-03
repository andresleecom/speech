from __future__ import annotations

from typing import Any

APP_NAME = "Speech"
LEGACY_APP_NAME = "WinWhisperDictate"
GITHUB_REPOSITORY = "andresleecom/speech"
PACKAGE_DISTRIBUTION = "speech"

# The app mark: the circle the tray draws while idle, reused as the window icon
# so the settings dialogs do not fall back to Tk's feather.
IDLE_ICON_COLOR = (128, 128, 128, 255)
_ICON_OUTLINE_COLOR = (255, 255, 255, 255)


def app_icon_image(
    size: int = 64,
    *,
    color: tuple[int, int, int, int] | None = None,
) -> Any:
    """Draw the app mark as a Pillow image.

    The tray passes its per-status color; everything else gets the idle circle.
    """
    from PIL import Image, ImageDraw

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
