import sys
import types

import pytest

from winwhisper.linux_shape import apply_image_shape, close_image_shape
from winwhisper.overlay import render_orb_frame


class FakeWindow:
    def __init__(self) -> None:
        self.rectangles: list[tuple[int, int, int, int]] = []

    def shape_rectangles(
        self,
        operation,
        destination_kind,
        ordering,
        x_offset,
        y_offset,
        rectangles,
    ) -> None:
        self.rectangles = list(rectangles)


class FakeDisplay:
    def __init__(self) -> None:
        self.window = FakeWindow()
        self.closed = False

    def has_extension(self, name: str) -> bool:
        return name == "SHAPE"

    def create_resource_object(self, resource_type: str, resource_id: int):
        return self.window

    def flush(self) -> None:
        return None

    def sync(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class FakeRoot:
    def update_idletasks(self) -> None:
        return None

    def winfo_id(self) -> int:
        return 123


@pytest.mark.parametrize(
    ("state", "phase"),
    [("recording", 0), ("recording", 8), ("transcribing", 0)],
)
def test_x11_shape_matches_rendered_overlay_alpha(monkeypatch, state, phase):
    display = FakeDisplay()
    display_opens: list[None] = []
    xlib = types.ModuleType("Xlib")
    xlib.X = types.SimpleNamespace(Unsorted=0)
    xlib.display = types.SimpleNamespace(
        Display=lambda: display_opens.append(None) or display
    )
    shape = types.SimpleNamespace(
        SO=types.SimpleNamespace(Set=0),
        SK=types.SimpleNamespace(Bounding=0),
    )
    xlib_ext = types.ModuleType("Xlib.ext")
    xlib_ext.shape = shape
    monkeypatch.setitem(sys.modules, "Xlib", xlib)
    monkeypatch.setitem(sys.modules, "Xlib.ext", xlib_ext)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":99")
    frame = render_orb_frame(state, phase=phase)
    root = FakeRoot()

    assert apply_image_shape(root, frame) is True
    assert apply_image_shape(root, frame) is True

    shaped_pixels = {
        (x, y)
        for left, top, width, height in display.window.rectangles
        for x in range(left, left + width)
        for y in range(top, top + height)
    }
    alpha = frame.getchannel("A")
    visible_pixels = {
        (x, y)
        for y in range(frame.height)
        for x in range(frame.width)
        if alpha.getpixel((x, y)) > 0
    }
    assert shaped_pixels == visible_pixels
    assert max(y for _x, y in shaped_pixels) >= 120
    assert display_opens == [None]
    assert display.closed is False

    close_image_shape(root)

    assert display.closed is True
