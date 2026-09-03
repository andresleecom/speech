"""Guards on scripts/make_icons.py and the committed icon artefacts."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def _load_make_icons():
    path = ROOT / "scripts" / "make_icons.py"
    spec = importlib.util.spec_from_file_location("make_icons", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_make_icons_writes_ico_with_all_seven_sizes(tmp_path):
    make_icons = _load_make_icons()
    path = tmp_path / "speech.ico"
    make_icons.write_ico(path)

    with Image.open(path) as image:
        sizes = sorted(image.info["sizes"])

    assert sizes == [
        (16, 16),
        (24, 24),
        (32, 32),
        (48, 48),
        (64, 64),
        (128, 128),
        (256, 256),
    ]


def test_make_icons_writes_icns_that_includes_512(tmp_path):
    make_icons = _load_make_icons()
    path = tmp_path / "speech.icns"
    make_icons.write_icns(path)

    with Image.open(path) as image:
        reported = image.info["sizes"]

    assert any(width == 512 and height == 512 for width, height, *_rest in reported)


def test_make_icons_linux_png_is_512_rgba_with_transparent_corner_and_red_centre(
    tmp_path,
):
    make_icons = _load_make_icons()
    path = tmp_path / "speech.png"
    make_icons.write_png(path, family="circle", size=512)

    with Image.open(path) as image:
        assert image.size == (512, 512)
        assert image.mode == "RGBA"
        assert image.getpixel((0, 0))[3] == 0
        # Geometric centre is the white stop glyph; sample the red button beside it.
        red = image.getpixel((256, 200))
        assert red[0] > 180
        assert red[1] < 100
        assert red[2] < 100
        assert red[3] == 255
        assert image.getpixel((256, 256))[:3] == (255, 255, 255)


def test_make_icons_16px_squircle_has_no_ring_outside_the_button():
    make_icons = _load_make_icons()
    image = make_icons.render_icon(family="squircle", size=16)

    # Design: button radius 72 on a 256 canvas → 72/256 of the 16 px icon.
    button_r = 72.0 / 256.0 * 16.0
    cx = cy = 7.5
    ringish = 0
    for y in range(16):
        for x in range(16):
            dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            if dist <= button_r + 0.75:
                continue
            r, g, b, a = image.getpixel((x, y))
            if a < 32:
                continue
            # Outside the button the surface is dark grey, never a red ring.
            if r > 140 and r > g + 40 and r > b + 40:
                ringish += 1

    assert ringish == 0
