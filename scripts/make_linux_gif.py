"""Generate docs/linux.gif - the Linux/X11 README dictation animation.

This reuses the shared illustration and real overlay renderer from
``make_demo_gif.py`` so the Linux demo stays visually consistent with the
Windows demo.

Run from the repository root inside the virtual environment:

    python scripts/make_linux_gif.py
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image

import make_demo_gif as demo


OUT_PATH = Path(__file__).resolve().parents[1] / "docs" / "linux.gif"


def main() -> None:
    demo.WINDOW_TITLE = "Text Editor — Linux (X11)"
    demo.WINDOW_BUTTONS = ["−", "□", "×"]
    background = demo.make_background()
    frames: list[Image.Image] = []
    durations: list[int] = []

    def add(frame: Image.Image, duration_ms: int) -> None:
        frames.append(frame)
        durations.append(duration_ms)

    for blink in (True, False, True, False):
        add(
            demo.compose(
                background,
                "1. Click where you want your words to go",
                blink,
                "",
                False,
                None,
            ),
            360,
        )

    for _ in range(3):
        add(
            demo.compose(
                background,
                "2. Linux: press Ctrl+Alt+Space",
                True,
                "",
                True,
                None,
            ),
            240,
        )

    for index in range(28):
        level = 0.35 + 0.45 * abs(math.sin(index / 3.5))
        orb = demo.render_orb_frame("recording", level, index)
        add(
            demo.compose(
                background,
                "3. Speak — Speech listens locally",
                True,
                "",
                False,
                orb,
            ),
            80,
        )

    for index in range(3):
        orb = demo.render_orb_frame("recording", 0.4, 28 + index)
        add(
            demo.compose(
                background,
                "4. Linux: press it again to stop",
                True,
                "",
                True,
                orb,
            ),
            240,
        )

    for index in range(14):
        orb = demo.render_orb_frame("transcribing", 0.0, index)
        add(
            demo.compose(
                background,
                "Transcribing on your machine…",
                True,
                "",
                False,
                orb,
            ),
            90,
        )

    for end in range(3, len(demo.DICTATED_TEXT) + 3, 3):
        add(
            demo.compose(
                background,
                "5. Your words appear right at your cursor",
                True,
                demo.DICTATED_TEXT[:end],
                False,
                None,
            ),
            70,
        )

    add(
        demo.compose(
            background,
            "Speech — local dictation on Linux",
            True,
            demo.DICTATED_TEXT,
            False,
            None,
        ),
        1500,
    )
    add(
        demo.compose(
            background,
            "Speech — local dictation on Linux",
            False,
            demo.DICTATED_TEXT,
            False,
            None,
        ),
        500,
    )

    palette = frames[10].quantize(colors=255)
    paletted = [
        frame.quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG)
        for frame in frames
    ]
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
