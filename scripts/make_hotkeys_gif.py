"""Generate the cross-platform hotkey animation used in the README.

Run from the repository root inside the development environment:

    python scripts/make_hotkeys_gif.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


WIDTH, HEIGHT = 920, 470
OUT_PATH = Path(__file__).resolve().parents[1] / "docs" / "hotkeys.gif"

BACKGROUND = (23, 27, 36)
PANEL = (247, 248, 250)
PANEL_BORDER = (219, 223, 230)
TEXT = (30, 34, 42)
MUTED = (98, 107, 121)
WINDOWS = (33, 122, 224)
MACOS = (16, 142, 125)
RECORDING = (220, 62, 62)


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        (
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "segoeuib.ttf",
            "DejaVuSans-Bold.ttf",
        )
        if bold
        else (
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "segoeui.ttf",
            "DejaVuSans.ttf",
        )
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _centered_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    text_font: ImageFont.FreeTypeFont,
    color: tuple[int, int, int],
) -> None:
    left, top, right, bottom = box
    text_box = draw.textbbox((0, 0), text, font=text_font)
    width = text_box[2] - text_box[0]
    height = text_box[3] - text_box[1]
    draw.text(
        (left + (right - left - width) / 2, top + (bottom - top - height) / 2 - 1),
        text,
        font=text_font,
        fill=color,
    )


def _key_width(label: str, key_font: ImageFont.FreeTypeFont) -> int:
    text_box = ImageDraw.Draw(Image.new("RGB", (1, 1))).textbbox(
        (0, 0), label, font=key_font
    )
    return max(54, text_box[2] - text_box[0] + 30)


def _draw_keys(
    draw: ImageDraw.ImageDraw,
    center_x: int,
    y: int,
    labels: tuple[str, ...],
    accent: tuple[int, int, int],
    pressed: bool,
) -> None:
    key_font = font(15, bold=True)
    widths = [_key_width(label, key_font) for label in labels]
    plus_width = 20
    total_width = sum(widths) + plus_width * (len(labels) - 1)
    x = center_x - total_width // 2

    for index, (label, width) in enumerate(zip(labels, widths)):
        fill = accent if pressed else (66, 73, 86)
        outline = tuple(min(255, component + 55) for component in accent) if pressed else (116, 124, 140)
        draw.rounded_rectangle(
            (x, y, x + width, y + 36),
            radius=6,
            fill=fill,
            outline=outline,
            width=1,
        )
        _centered_text(draw, (x, y, x + width, y + 36), label, key_font, (255, 255, 255))
        x += width
        if index < len(labels) - 1:
            _centered_text(draw, (x, y, x + plus_width, y + 36), "+", font(18, bold=True), (109, 116, 132))
            x += plus_width


def _draw_recording_indicator(
    draw: ImageDraw.ImageDraw,
    center_x: int,
    center_y: int,
    accent: tuple[int, int, int],
    active: bool,
    pulse: int,
) -> None:
    radius = 24 + (pulse % 3 if active else 0)
    ring = tuple(min(255, component + 25) for component in accent)
    draw.ellipse(
        (center_x - radius, center_y - radius, center_x + radius, center_y + radius),
        fill=(255, 255, 255),
        outline=ring,
        width=3,
    )
    inner = RECORDING if active else (157, 164, 176)
    draw.ellipse(
        (center_x - 13, center_y - 13, center_x + 13, center_y + 13),
        fill=inner,
    )
    if active:
        draw.rounded_rectangle(
            (center_x - 5, center_y - 5, center_x + 5, center_y + 5),
            radius=2,
            fill=(255, 255, 255),
        )


def _draw_panel(
    image: Image.Image,
    box: tuple[int, int, int, int],
    platform_name: str,
    shortcut: tuple[str, ...],
    accent: tuple[int, int, int],
    pressed: bool,
    pulse: int,
) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    left, top, right, bottom = box
    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        (left, top + 7, right, bottom + 9), radius=12, fill=(0, 0, 0, 70)
    )
    image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(7)))

    draw.rounded_rectangle(box, radius=12, fill=PANEL, outline=PANEL_BORDER, width=1)
    draw.rounded_rectangle((left, top, right, top + 45), radius=12, fill=(236, 239, 244))
    draw.rectangle((left, top + 31, right, top + 45), fill=(236, 239, 244))
    draw.ellipse((left + 18, top + 16, left + 27, top + 25), fill=accent)
    draw.text((left + 39, top + 11), platform_name, font=font(17, bold=True), fill=TEXT)
    draw.text((left + 39, top + 29), "Start / stop recording", font=font(12), fill=MUTED)

    center_x = (left + right) // 2
    _draw_recording_indicator(draw, center_x, top + 112, accent, pressed, pulse)
    state = "Recording" if pressed else "Ready to dictate"
    _centered_text(draw, (left, top + 149, right, top + 174), state, font(15, bold=True), TEXT)
    _draw_keys(draw, center_x, top + 191, shortcut, accent, pressed)
    _centered_text(
        draw,
        (left + 15, bottom - 45, right - 15, bottom - 18),
        "Press the same shortcut again to stop",
        font(12),
        MUTED,
    )


def _frame(windows_pressed: bool, macos_pressed: bool, pulse: int) -> Image.Image:
    image = Image.new("RGBA", (WIDTH, HEIGHT), BACKGROUND + (255,))
    draw = ImageDraw.Draw(image)
    _centered_text(
        draw,
        (0, 18, WIDTH, 48),
        "The same action, with platform-native keys",
        font(22, bold=True),
        (246, 248, 252),
    )
    _centered_text(
        draw,
        (0, 51, WIDTH, 75),
        "Press once to record. Press again to transcribe and paste.",
        font(14),
        (184, 192, 207),
    )
    _draw_panel(
        image,
        (46, 102, 442, 390),
        "Windows",
        ("Ctrl", "Alt", "Space"),
        WINDOWS,
        windows_pressed,
        pulse,
    )
    _draw_panel(
        image,
        (478, 102, 874, 390),
        "macOS",
        ("Control", "Option", "Space"),
        MACOS,
        macos_pressed,
        pulse,
    )
    _centered_text(
        draw,
        (0, 414, WIDTH, 445),
        "Hotkeys can be changed from Speech > Hotkey Settings...",
        font(13),
        (184, 192, 207),
    )
    return image.convert("RGB")


def main() -> None:
    frames: list[Image.Image] = []
    durations: list[int] = []

    def add(windows_pressed: bool, macos_pressed: bool, pulse: int, duration: int) -> None:
        frames.append(_frame(windows_pressed, macos_pressed, pulse))
        durations.append(duration)

    add(False, False, 0, 1100)
    for pulse in range(3):
        add(True, False, pulse, 180)
    add(False, False, 0, 300)
    for pulse in range(3):
        add(False, True, pulse, 180)
    add(False, False, 0, 300)
    for pulse in range(5):
        add(True, True, pulse, 150)
    add(False, False, 0, 1400)

    palette = frames[0].quantize(colors=255)
    paletted = [frame.quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG) for frame in frames]
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    paletted[0].save(
        OUT_PATH,
        save_all=True,
        append_images=paletted[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    print(f"wrote {OUT_PATH} ({OUT_PATH.stat().st_size / 1024:.0f} KiB, {len(frames)} frames)")


if __name__ == "__main__":
    main()
