# Task 02 follow-up: legacy index hints must fall back visibly; keep toasts short

You are the MAP executor (Grok CLI). Obey HARD RULES. No git. End with ## REPORT.

## Goal
Two corrections to the task 02 work already in the working tree (do not redo it). First, a settings file that has `audio_input_device: 3` and no `audio_input_device_name` (the owner's real file today, where index 3 no longer exists) must resolve to System Default with `fallback=True` so the "Using System Default because ..." toast fires; it currently resolves as if the user had chosen System Default. Second, the user-facing error toast must stay short; PortAudio details belong in the log.

## Context - read these first
- `src/winwhisper/audio_inputs.py`: `resolve_input_device` returns `fallback=False` whenever `name is None`.
- `src/winwhisper/recorder.py`: `RecorderError` messages now embed `{exc.__class__.__name__}: {exc}; device=..., label=...` (three sites: `Recorder.start_recording`, `MicrophoneTest.start`) and `src/winwhisper/wake_word_source.py` (`SounddeviceSource.start`).
- `src/winwhisper/main.py`: `toggle()` logs the recorder exception with `exc_info` and toasts `str(start_error)`; `_maybe_toast_microphone_fallback` reads `recorder.last_resolution`.
- Tests: `tests/test_audio_inputs.py`, `tests/test_recorder.py`, `tests/test_overlay_flow.py`.

## Scope - you may edit
- `src/winwhisper/audio_inputs.py`, `src/winwhisper/recorder.py`, `src/winwhisper/wake_word_source.py`, `src/winwhisper/main.py`
- `tests/test_audio_inputs.py`, `tests/test_recorder.py`, `tests/test_overlay_flow.py`, `tests/test_wake_word.py`

## Out of scope - do not touch
- Everything else. Do not restructure the task 02 code beyond these two changes.

## Steps
1. `resolve_input_device`: when `name is None` and `index_hint is None` return System Default with `fallback=False` (user choice). When `name is None` and `index_hint` matches a live input row, return that row (`fallback=False`). When `name is None` and the hint matches nothing, return System Default with `fallback=True` and reason `Microphone [<hint>] is unavailable`. Keep the named paths unchanged.
2. `RecorderError`: add an optional `details: str = ""` attribute (constructor `RecorderError(message, details="")`, `str()` stays the message). At the three raise sites keep the short message ending in `(<ExceptionClassName>).` as before the task 02 change and put `<ExceptionClassName>: <exc text>; device=<index>; label=<label>` into `details`.
3. `main.py` `toggle()`: when the start error is an exception, log `"%s %s"` with the message and `getattr(exc, "details", "")` using `exc_info`, and toast only the message. `_maybe_toast_microphone_fallback`: when the saved name is None, say `Using System Default because the saved microphone [<hint>] is unavailable`.
4. Tests: `resolve_input_device(None, None, 3, devices)` with no index 3 -> `fallback=True`; `(None, None, 2, devices)` with a live index 2 -> index 2, `fallback=False`; `(None, None, None, ...)` -> `fallback=False`; the recorder error test asserts the short message and the `details` content separately; the controller fallback toast test covers the name-less legacy case.

## Verify before reporting
Run: `env -u SSLKEYLOGFILE .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
Run: `env -u SSLKEYLOGFILE .venv/Scripts/python.exe -c "from winwhisper.audio_inputs import list_audio_input_devices, resolve_input_device; d=list_audio_input_devices(); print(resolve_input_device(None, None, 3, d)); print(resolve_input_device(None, None, 2, d))"`
Paste both outputs in your REPORT under PROOF.

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
