"""Generate docs/demo.gif - the README demo of dictating at the cursor.

The animation is drawn programmatically (no screen recording) and reuses the
app's real overlay renderer, so the orb in the demo is the actual product UI.

Run from the repository root inside the virtual environment:

    python scripts/make_demo_gif.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from winwhisper.overlay import render_orb_frame  # noqa: E402

WIDTH, HEIGHT = 720, 405
OUT_PATH = Path(__file__).resolve().parents[1] / "docs" / "demo.gif"

WINDOW_BOX = (60, 46, 660, 336)  # left, top, right, bottom
TITLEBAR_H = 34
TEXT_X = 92
LINE1_Y = 108
LINE2_Y = 152
CARET_H = 22

EXISTING_TEXT = "Reunión de hoy:"
DICTATED_TEXT = "Hola equipo, aquí van las notas de la reunión."
CAPTION_Y = 12
KEYS_Y = 352

KEY_LABELS = ["Ctrl", "Alt", "Space"]

ACCENT = (219, 66, 65)
CAPTION_COLOR = (232, 232, 236)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "segoeuib.ttf" if bold else "segoeui.ttf"
    try:
        return ImageFont.truetype(name, size)
    except Exception:
        return ImageFont.load_default()


def make_background() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT))
    top, bottom = (28, 30, 40), (37, 41, 56)
    for y in range(HEIGHT):
        t = y / HEIGHT
        row = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom))
        for_row = Image.new("RGB", (WIDTH, 1), row)
        image.paste(for_row, (0, y))

    draw = ImageDraw.Draw(image, "RGBA")

    # Window drop shadow.
    shadow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [WINDOW_BOX[0] - 4, WINDOW_BOX[1] + 2, WINDOW_BOX[2] + 4, WINDOW_BOX[3] + 10],
        radius=12,
        fill=(0, 0, 0, 110),
    )
    image.paste(
        Image.alpha_composite(image.convert("RGBA"), shadow.filter(ImageFilter.GaussianBlur(6)))
    )

    draw = ImageDraw.Draw(image, "RGBA")
    # Editor window.
    draw.rounded_rectangle(WINDOW_BOX, radius=10, fill=(250, 250, 252))
    draw.rounded_rectangle(
        [WINDOW_BOX[0], WINDOW_BOX[1], WINDOW_BOX[2], WINDOW_BOX[1] + TITLEBAR_H],
        radius=10,
        fill=(236, 236, 241),
    )
    draw.rectangle(
        [WINDOW_BOX[0], WINDOW_BOX[1] + TITLEBAR_H - 12, WINDOW_BOX[2], WINDOW_BOX[1] + TITLEBAR_H],
        fill=(236, 236, 241),
    )
    draw.text(
        (WINDOW_BOX[0] + 14, WINDOW_BOX[1] + 8),
        "Notas — cualquier aplicación",
        font=font(14),
        fill=(90, 90, 100),
    )
    # Window buttons (ASCII-safe glyphs render reliably in Segoe UI).
    glyph_font = font(13)
    for index, glyph in enumerate(["—", "□", "×"]):
        draw.text(
            (WINDOW_BOX[2] - 74 + index * 26, WINDOW_BOX[1] + 8),
            glyph,
            font=glyph_font,
            fill=(120, 120, 130),
        )
    # Existing document text.
    draw.text((TEXT_X, LINE1_Y), EXISTING_TEXT, font=font(18), fill=(40, 42, 48))
    return image


def draw_keycaps(draw: ImageDraw.ImageDraw, pressed: bool) -> None:
    key_font = font(14, bold=True)
    pad_x, height = 12, 30
    widths = []
    for label in KEY_LABELS:
        box = draw.textbbox((0, 0), label, font=key_font)
        widths.append(box[2] - box[0] + pad_x * 2)
    plus_w = 16
    total = sum(widths) + plus_w * (len(KEY_LABELS) - 1)
    x = (WIDTH - total) // 2
    for index, (label, key_w) in enumerate(zip(KEY_LABELS, widths)):
        fill = ACCENT if pressed else (58, 60, 72)
        outline = (255, 130, 128) if pressed else (96, 98, 112)
        draw.rounded_rectangle(
            [x, KEYS_Y, x + key_w, KEYS_Y + height],
            radius=6,
            fill=fill,
            outline=outline,
        )
        box = draw.textbbox((0, 0), label, font=key_font)
        draw.text(
            (x + (key_w - (box[2] - box[0])) / 2, KEYS_Y + 6),
            label,
            font=key_font,
            fill=(255, 255, 255),
        )
        x += key_w
        if index < len(KEY_LABELS) - 1:
            draw.text((x + 3, KEYS_Y + 4), "+", font=font(16, bold=True), fill=(180, 182, 192))
            x += plus_w


def compose(
    background: Image.Image,
    caption: str,
    caret_on: bool,
    typed: str,
    keys_pressed: bool,
    orb: Image.Image | None,
) -> Image.Image:
    frame = background.copy().convert("RGBA")
    draw = ImageDraw.Draw(frame)

    text_font = font(18)
    if typed:
        draw.text((TEXT_X, LINE2_Y), typed, font=text_font, fill=(40, 42, 48))
    caret_x = TEXT_X + (draw.textlength(typed, font=text_font) if typed else 0)
    if caret_on:
        draw.rectangle([caret_x + 1, LINE2_Y + 2, caret_x + 3, LINE2_Y + CARET_H], fill=(30, 32, 40))

    if orb is not None:
        # Mirror the app: orb floats to the right of the caret, vertically centered.
        frame.alpha_composite(orb, (int(caret_x) + 16, LINE2_Y + 12 - 76))

    caption_font = font(16)
    caption_w = draw.textlength(caption, font=caption_font)
    draw.text(((WIDTH - caption_w) / 2, CAPTION_Y), caption, font=caption_font, fill=CAPTION_COLOR)

    draw_keycaps(draw, keys_pressed)
    return frame.convert("RGB")


def main() -> None:
    background = make_background()
    frames: list[Image.Image] = []
    durations: list[int] = []

    def add(frame: Image.Image, duration_ms: int) -> None:
        frames.append(frame)
        durations.append(duration_ms)

    # 1. Blinking caret: put your cursor anywhere.
    for blink in (True, False, True, False):
        add(
            compose(background, "1. Click where you want your words to go", blink, "", False, None),
            360,
        )

    # 2. Press the hotkey.
    for _ in range(3):
        add(compose(background, "2. Press Ctrl+Alt+Space", True, "", True, None), 240)

    # 3. Recording: live orb with sonar rings.
    for i in range(28):
        level = 0.35 + 0.45 * abs(math.sin(i / 3.5))
        orb = render_orb_frame("recording", level, i)
        add(compose(background, "3. Speak — Speech listens locally", True, "", False, orb), 80)

    # 4. Press again to stop.
    for i in range(3):
        orb = render_orb_frame("recording", 0.4, 28 + i)
        add(compose(background, "4. Press Ctrl+Alt+Space again to stop", True, "", True, orb), 240)

    # 5. Transcribing spinner.
    for i in range(14):
        orb = render_orb_frame("transcribing", 0.0, i)
        add(compose(background, "Transcribing on your machine…", True, "", False, orb), 90)

    # 6. The text lands at the cursor.
    step = 3
    for end in range(step, len(DICTATED_TEXT) + step, step):
        typed = DICTATED_TEXT[:end]
        add(
            compose(background, "5. Your words appear right at your cursor", True, typed, False, None),
            70,
        )

    # 7. Hold the final frame.
    add(compose(background, "Speech — local dictation for Windows", True, DICTATED_TEXT, False, None), 1500)
    add(compose(background, "Speech — local dictation for Windows", False, DICTATED_TEXT, False, None), 500)

    # Shared palette keeps colors stable across frames.
    master = frames[10].quantize(colors=255)
    paletted = [frame.quantize(palette=master, dither=Image.Dither.FLOYDSTEINBERG) for frame in frames]

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
