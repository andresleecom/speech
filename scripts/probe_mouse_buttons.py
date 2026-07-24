"""Report the mouse buttons this machine can actually see.

Extra buttons on gaming and productivity mice often do not reach the OS as
mouse events at all. Vendor software (Logitech Options+, Razer Synapse) may be
sending a keyboard macro instead, in which case Speech can never bind them as
mouse buttons. Run this, press every button you care about, and read the names.

    python scripts/probe_mouse_buttons.py
"""
from __future__ import annotations

import sys
import time

try:
    from pynput import mouse
except ImportError:
    print("pynput is not installed. Run: pip install pynput")
    raise SystemExit(1)

SECONDS = 25
seen: dict[str, int] = {}


def on_click(x: int, y: int, button: object, pressed: bool) -> None:
    if not pressed:
        return
    name = getattr(button, "name", str(button))
    seen[name] = seen.get(name, 0) + 1
    print(f"  button={name:<10} raw={button!r}", flush=True)


print(f"Platform: {sys.platform}")
print(f"Press each mouse button you might want to bind. Listening {SECONDS}s...")
print("(Left and right clicks are included so you can confirm the probe works.)\n", flush=True)

listener = mouse.Listener(on_click=on_click)
listener.start()
time.sleep(SECONDS)
listener.stop()

print("\n--- summary ---")
if not seen:
    print("No mouse buttons were seen at all.")
    print("On macOS, grant Input Monitoring. On Linux, an X11 session is required.")
else:
    for name, count in sorted(seen.items(), key=lambda item: -item[1]):
        print(f"  {name:<10} {count} press(es)")
    extras = sorted(set(seen) - {"left", "right", "middle"})
    print()
    if extras:
        print(f"Bindable extra buttons: {', '.join(extras)}")
    else:
        print("No extra buttons reached the OS as mouse events.")
        print("If you pressed side buttons, vendor software is likely remapping them")
        print("to keystrokes; bind those as normal keyboard shortcuts instead.")
