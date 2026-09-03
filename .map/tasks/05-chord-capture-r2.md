# Task 05 follow-up: make OEM key mapping independent of the active input language

You are the MAP executor. Obey HARD RULES. No git. End with ## REPORT.

## Goal
The task 05 work resolves characters and AltGr collisions against `GetKeyboardLayout(0)`, the calling thread's layout. On the owner's machine two input languages are installed, en-US (default, 0x04090409) and es-ES (0x040A040A), and Windows switches them per window. Measured: under en-US `<` maps to Shift+0xBC (the comma key) and `ñ`/`º` do not map at all; under es-ES `<` is 0xE2 unshifted, `ñ` is 0xC0, `º` is 0xDC, and AltGr+E types `€`. A chord saved as `<` must always bind the physical `<` key (0xE2), and Ctrl+Alt+E must be rejected because es-ES types `€` with it even when en-US is active. Do not redo the rest of task 05.

## Context - read these first
- `src/winwhisper/hotkeys.py`: `_vk_from_layout_character`, `altgr_produces_character`, `trigger_to_vk`.
- `src/winwhisper/hotkey_settings.py`: `combo_from_key_event` (Windows branch maps `keycode` to a trigger; OEM keycodes need a character) and the AltGr rejection in `normalize_hotkey_input`.
- Win32 facts: `GetKeyboardLayoutList(0, NULL)` returns the count and `GetKeyboardLayoutList(n, arr)` fills HKLs; `VkKeyScanExW` returns `0xFFFF` when unmapped, else low byte = VK and high byte = shift state (0 means unshifted); `ToUnicodeEx(vk, scancode, keystate, buf, len, 0, hkl)` with an empty key state gives the unshifted character; `MapVirtualKeyExW(vk, 0, hkl)` gives the scan code. Use private `ctypes.WinDLL("user32")` handles only.
- Tests: `tests/test_hotkeys.py`, `tests/test_hotkey_settings.py` (existing fakes for user32).

## Scope - you may edit
- `src/winwhisper/hotkeys.py`, `src/winwhisper/hotkey_settings.py`
- `tests/test_hotkeys.py`, `tests/test_hotkey_settings.py`

## Out of scope - do not touch
- Everything else.

## Steps
1. `hotkeys.py`: add `_installed_layouts() -> tuple[int, ...]` (current thread layout first, then the others from `GetKeyboardLayoutList`, de-duplicated). `_vk_from_layout_character(ch)`: query every installed layout; return the VK of the first layout where the character is unshifted (high byte 0), else the first layout where it maps at all, else None. `altgr_produces_character(vk)` returns the first character any installed layout types for Ctrl+Alt+vk (current layout first), else None.
2. Add `character_for_virtual_key(vk) -> str | None`: for each installed layout (current first), take the unshifted character from `ToUnicodeEx` with an empty key state and accept it only when `VkKeyScanExW(char, layout) & 0xFF == vk` (the round trip lands on the same physical key); return the first accepted printable non-space character, else None.
3. `hotkey_settings.py` `combo_from_key_event` (Windows branch): for keycodes that are not letters, digits, function keys, or entries of `_VK_TO_TRIGGER`, use `character_for_virtual_key(keycode)` before any keysym-based fallback. Keep the AltGr rejection message naming the produced character.
4. Tests with a fake user32 exposing two layouts (0x04090409 current, 0x040A040A installed) and the measured tables above: `trigger_to_vk("<") == 0xE2` while en-US is current; `trigger_to_vk("ñ") == 0xC0`; `trigger_to_vk("º") == 0xDC`; `character_for_virtual_key(0xE2) == "<"` while en-US is current (en-US round trip fails because `\` maps to 0xDC, es-ES succeeds); `normalize_hotkey_input("<ctrl>+<alt>+e", platform="win32")` is rejected with `€` in the message while en-US is current; `combo_from_key_event(keycode=0xE2, keysym="backslash", state=0x20004, platform="win32")` yields `<ctrl>+<alt>+<`.

## Verify before reporting
Run: `env -u SSLKEYLOGFILE .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
Run: `PYTHONUTF8=1 env -u SSLKEYLOGFILE .venv/Scripts/python.exe -c "from winwhisper.hotkeys import trigger_to_vk, altgr_produces_character, character_for_virtual_key; print(hex(trigger_to_vk('<')), hex(trigger_to_vk('ñ')), hex(trigger_to_vk('º')), altgr_produces_character(0x45), character_for_virtual_key(0xE2))"`
Expected on this machine: `0xe2 0xc0 0xdc € <`. Paste both outputs in your REPORT under PROOF.

HARD RULES - violating any of these means your work is discarded:
- NO git commands of any kind (no commit, branch, push, reset, checkout, stash).
- NO dependency changes: no package installs, no lockfile edits, no tool installs.
- Edit ONLY within the scope listed above. If the fix requires touching anything else, STOP and explain in your REPORT instead of doing it.
- If blocked or uncertain, STOP and report - do not improvise around the spec.
- End your output with:
  ## REPORT
  STATUS: done | blocked
  FILES TOUCHED: <list>
  PROOF: <output of the verification commands you were asked to run>
  NOTES: <≤10 lines: decisions made, anything the reviewer must know>
