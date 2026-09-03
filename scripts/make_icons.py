"""Render Speech app icons from the approved SVG geometry.

Design source: .lavish/speech-icon.html <defs> (256-unit canvas).
Standalone SVG mirrors live in packaging/icons/.

No browser, cairo, or extra packages - Pillow + numpy only.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[1]
CANVAS = 256.0
SUPERSAMPLE = 4

# Gradients from the design defs.
SURF_DARK_INNER = (0x33, 0x33, 0x3B, 255)
SURF_DARK_OUTER = (0x1B, 0x1B, 0x20, 255)
BTN_RED_TOP = (0xE2, 0x4C, 0x4A, 255)
BTN_RED_BOTTOM = (0xCC, 0x36, 0x35, 255)
MINI_SURFACE = (0x1D, 0x1D, 0x22, 255)
MINI_BUTTON = (0xDB, 0x42, 0x41, 255)
WHITE = (255, 255, 255, 255)

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
ICNS_SIZES = (16, 32, 64, 128, 256, 512)


def _scale(units: float, px: int) -> float:
    return units * (SUPERSAMPLE * px) / CANVAS


def _variant_for_size(size: int) -> str:
    """Pick design variant: mini (16), core (24/32), or full rings (48+)."""
    if size <= 16:
        return "mini"
    if size <= 32:
        return "core"
    return "full"


def _lerp_color(
    c0: tuple[int, int, int, int],
    c1: tuple[int, int, int, int],
    t: np.ndarray,
) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)[..., None]
    a = np.asarray(c0, dtype=np.float64)
    b = np.asarray(c1, dtype=np.float64)
    return (a + (b - a) * t).astype(np.uint8)


def _radial_surf(
    width: int,
    height: int,
    bbox: tuple[float, float, float, float],
) -> np.ndarray:
    """Radial gradient: centre at 0.35, 0.25 of bbox; radius 1.0 of bbox side."""
    left, top, right, bottom = bbox
    bw = right - left
    bh = bottom - top
    cx = left + 0.35 * bw
    cy = top + 0.25 * bh
    # objectBoundingBox r=1 → radius equals the bbox width (square shapes).
    radius = bw
    ys, xs = np.ogrid[0:height, 0:width]
    dist = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2) / radius
    return _lerp_color(SURF_DARK_INNER, SURF_DARK_OUTER, dist)


def _linear_btn(
    width: int,
    height: int,
    bbox: tuple[float, float, float, float],
) -> np.ndarray:
    """Vertical linear gradient across the shape bbox."""
    _left, top, _right, bottom = bbox
    ys = np.arange(height, dtype=np.float64)[:, None]
    t = (ys - top) / max(bottom - top, 1.0)
    t = np.broadcast_to(t, (height, width))
    return _lerp_color(BTN_RED_TOP, BTN_RED_BOTTOM, t)


def _mask_ellipse(
    size: tuple[int, int],
    bbox: tuple[float, float, float, float],
) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).ellipse(bbox, fill=255)
    return mask


def _mask_rounded_rect(
    size: tuple[int, int],
    bbox: tuple[float, float, float, float],
    radius: float,
) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(bbox, radius=radius, fill=255)
    return mask


def _paste_masked(
    canvas: Image.Image,
    rgba: np.ndarray,
    mask: Image.Image,
) -> None:
    layer = Image.fromarray(rgba, mode="RGBA")
    canvas.paste(layer, (0, 0), mask=mask)


def _stroke_ellipse(
    draw: ImageDraw.ImageDraw,
    bbox: tuple[float, float, float, float],
    color: tuple[int, int, int, int],
    width: float,
) -> None:
    w = max(1, int(round(width)))
    draw.ellipse(bbox, outline=color, width=w)


def _stroke_rounded_rect(
    draw: ImageDraw.ImageDraw,
    bbox: tuple[float, float, float, float],
    radius: float,
    color: tuple[int, int, int, int],
    width: float,
) -> None:
    w = max(1, int(round(width)))
    draw.rounded_rectangle(bbox, radius=radius, outline=color, width=w)


def _circle_bbox(cx: float, cy: float, r: float) -> tuple[float, float, float, float]:
    return (cx - r, cy - r, cx + r, cy + r)


def _draw_stop_glyph(
    draw: ImageDraw.ImageDraw,
    px: int,
    *,
    x: float,
    y: float,
    side: float,
    rx: float,
) -> None:
    s = _scale(1.0, px)
    box = (x * s, y * s, (x + side) * s, (y + side) * s)
    draw.rounded_rectangle(box, radius=rx * s, fill=WHITE)


def render_icon(*, family: str, size: int) -> Image.Image:
    """Render one icon at ``size`` px for ``family`` ('circle' or 'squircle')."""
    if family not in ("circle", "squircle"):
        raise ValueError(f"unknown family: {family!r}")
    if size < 1:
        raise ValueError(f"size must be positive, got {size}")

    hi = SUPERSAMPLE * size
    canvas = Image.new("RGBA", (hi, hi), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    s = _scale(1.0, size)
    cx = 128.0 * s
    cy = 128.0 * s
    variant = _variant_for_size(size)

    if variant == "mini":
        if family == "circle":
            surf_r = 104.0 * s
            mask = _mask_ellipse((hi, hi), _circle_bbox(cx, cy, surf_r))
            flat = np.zeros((hi, hi, 4), dtype=np.uint8)
            flat[:] = MINI_SURFACE
            _paste_masked(canvas, flat, mask)
        else:
            bbox = (8.0 * s, 8.0 * s, 248.0 * s, 248.0 * s)
            rx = 56.0 * s
            mask = _mask_rounded_rect((hi, hi), bbox, rx)
            flat = np.zeros((hi, hi, 4), dtype=np.uint8)
            flat[:] = MINI_SURFACE
            _paste_masked(canvas, flat, mask)
        btn_r = 72.0 * s
        btn_mask = _mask_ellipse((hi, hi), _circle_bbox(cx, cy, btn_r))
        flat = np.zeros((hi, hi, 4), dtype=np.uint8)
        flat[:] = MINI_BUTTON
        _paste_masked(canvas, flat, btn_mask)
        _draw_stop_glyph(draw, size, x=102.0, y=102.0, side=52.0, rx=12.0)
    elif variant == "core":
        if family == "circle":
            surf_r = 88.0 * s
            surf_bbox = _circle_bbox(cx, cy, surf_r)
            mask = _mask_ellipse((hi, hi), surf_bbox)
            _paste_masked(canvas, _radial_surf(hi, hi, surf_bbox), mask)
            _stroke_ellipse(
                draw,
                surf_bbox,
                (255, 255, 255, int(round(0.14 * 255))),
                3.0 * s,
            )
        else:
            # Squircle background from orb-squircle; button/glyph from orb-core.
            surf_bbox = (8.0 * s, 8.0 * s, 248.0 * s, 248.0 * s)
            rx = 56.0 * s
            mask = _mask_rounded_rect((hi, hi), surf_bbox, rx)
            _paste_masked(canvas, _radial_surf(hi, hi, surf_bbox), mask)
            _stroke_rounded_rect(
                draw,
                surf_bbox,
                rx,
                (255, 255, 255, int(round(0.10 * 255))),
                2.0 * s,
            )
        btn_r = 54.0 * s
        btn_bbox = _circle_bbox(cx, cy, btn_r)
        btn_mask = _mask_ellipse((hi, hi), btn_bbox)
        _paste_masked(canvas, _linear_btn(hi, hi, btn_bbox), btn_mask)
        _draw_stop_glyph(draw, size, x=113.0, y=113.0, side=30.0, rx=7.0)
    else:
        # full (rings)
        if family == "circle":
            _stroke_ellipse(
                draw,
                _circle_bbox(cx, cy, 112.0 * s),
                (219, 66, 65, int(round(0.20 * 255))),
                7.0 * s,
            )
            _stroke_ellipse(
                draw,
                _circle_bbox(cx, cy, 96.0 * s),
                (219, 66, 65, int(round(0.40 * 255))),
                7.0 * s,
            )
            surf_r = 76.0 * s
            surf_bbox = _circle_bbox(cx, cy, surf_r)
            mask = _mask_ellipse((hi, hi), surf_bbox)
            _paste_masked(canvas, _radial_surf(hi, hi, surf_bbox), mask)
            _stroke_ellipse(
                draw,
                surf_bbox,
                (255, 255, 255, int(round(0.14 * 255))),
                2.5 * s,
            )
        else:
            surf_bbox = (8.0 * s, 8.0 * s, 248.0 * s, 248.0 * s)
            rx = 56.0 * s
            mask = _mask_rounded_rect((hi, hi), surf_bbox, rx)
            _paste_masked(canvas, _radial_surf(hi, hi, surf_bbox), mask)
            _stroke_rounded_rect(
                draw,
                surf_bbox,
                rx,
                (255, 255, 255, int(round(0.10 * 255))),
                2.0 * s,
            )
            _stroke_ellipse(
                draw,
                _circle_bbox(cx, cy, 96.0 * s),
                (219, 66, 65, int(round(0.35 * 255))),
                7.0 * s,
            )
        btn_r = 47.0 * s
        btn_bbox = _circle_bbox(cx, cy, btn_r)
        btn_mask = _mask_ellipse((hi, hi), btn_bbox)
        _paste_masked(canvas, _linear_btn(hi, hi, btn_bbox), btn_mask)
        _draw_stop_glyph(draw, size, x=114.5, y=114.5, side=27.0, rx=6.5)

    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def write_ico(path: Path, sizes: tuple[int, ...] = ICO_SIZES) -> Path:
    """Write a multi-size Windows .ico (squircle family)."""
    images = [render_icon(family="squircle", size=s) for s in sorted(sizes)]
    largest = images[-1]
    path.parent.mkdir(parents=True, exist_ok=True)
    largest.save(
        path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[:-1],
    )
    return path


def write_icns(path: Path, sizes: tuple[int, ...] = ICNS_SIZES) -> Path:
    """Write a multi-size macOS .icns (circular family)."""
    images = [render_icon(family="circle", size=s) for s in sorted(sizes)]
    by_width = {im.width: im for im in images}
    largest = by_width[max(by_width)]
    append = [im for w, im in sorted(by_width.items()) if w != largest.width]
    path.parent.mkdir(parents=True, exist_ok=True)
    largest.save(path, format="ICNS", append_images=append)
    return path


def write_png(path: Path, *, family: str, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    render_icon(family=family, size=size).save(path, format="PNG")
    return path


def main() -> None:
    written: list[Path] = []
    written.append(write_ico(REPO_ROOT / "packaging" / "windows" / "speech.ico"))
    written.append(write_icns(REPO_ROOT / "packaging" / "macos" / "speech.icns"))
    written.append(
        write_png(
            REPO_ROOT / "packaging" / "linux" / "speech.png",
            family="circle",
            size=512,
        )
    )
    written.append(
        write_png(
            REPO_ROOT / "src" / "winwhisper" / "assets" / "app-icon-256.png",
            family="circle",
            size=256,
        )
    )
    for path in written:
        rel = path.relative_to(REPO_ROOT)
        print(f"wrote {rel}")


if __name__ == "__main__":
    main()
