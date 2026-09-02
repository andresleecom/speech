# Task 03: Diagnose silent and dead takes instead of a blanket "No speech detected"

You are the MAP executor (Grok CLI). Obey HARD RULES. No git. End with ## REPORT.

## Goal
A take that captured zero frames, or only digital silence, tells the user which microphone failed instead of "No speech detected". 54 of the last 293 takes ended with that toast; 16 were 44-byte WAVs from a dead device and about 30 were full-length silent streams. Each take also logs one timing summary line.

## Context - read these first
- `src/winwhisper/recorder.py`: `Recorder` keeps a smoothed `_level` and `_sample_count` (reset in `start_recording` and again in `stop_recording` ~line 137-141 before any caller can read it). `MicrophoneTest` already tracks `_peak_level` (~line 256-278): copy that pattern. Task 02 added `last_resolution` with a `label` on the recorder.
- `src/winwhisper/main.py`: `_stop_and_process` (~line 963) logs `Microphone stopped in %.2fs; audio_file=%s; bytes=%s`, then transcribes, and toasts `No speech detected` in two places (~line 1000 and ~1015). `toggle()` logs `Recording started`. `_handle_error` at ~line 1158.
- `tests/test_overlay_flow.py`: `FakeRecorder` and the controller harness (the pattern for behaviour tests). `tests/test_recorder.py` for recorder unit tests with a fake sounddevice.

## Scope - you may edit
- `src/winwhisper/recorder.py`, `src/winwhisper/main.py`
- `tests/test_recorder.py`, `tests/test_overlay_flow.py`

## Out of scope - do not touch
- `recorder_mac.py` (macOS parity is a later task), `transcriber.py`, `wake_word*.py`, `tray.py`, `config.py`, `audio_inputs.py`, docs, workflows.

## Steps
1. `recorder.py`: track `_peak_level` next to `_level` in the callback. In `stop_recording`, snapshot `frames = self._sample_count`, `peak = self._peak_level`, and the elapsed open-to-first-block time before the reset, and expose `last_take_stats() -> TakeStats(frames: int, peak: float, seconds: float, first_block_ms: float | None, device_label: str)`. Record `time.perf_counter()` at stream start and at the first callback; if no block arrives within 500 ms of `stream.start()`, log a WARNING naming the device label (a timer thread or a check in `stop_recording` is fine; do not block the hotkey thread).
2. `main.py` `_stop_and_process`: read `stats = getattr(self.recorder, "last_take_stats", lambda: None)()` right after `stop_recording`. If `stats` exists and `stats.frames == 0`: skip transcription, delete the WAV, log `Nothing was captured from <label>`, and toast `Nothing was captured from <label>. Open Microphone and pick System Default or another device.` If the transcription comes back empty and `stats.peak == 0.0`: toast `<label> delivered silence. Check the microphone or pick another one.` Otherwise keep `No speech detected`. Apply the same rule to the second empty branch (cleaned text empty).
3. `main.py`: log one INFO line per take at the end of processing: `Take timing: to_stream_ms=%d first_block_ms=%s record_s=%.1f stop_ms=%d transcribe_ms=%d clean_ms=%d paste_ms=%d frames=%d peak=%.3f device=%s`. Use `perf_counter` stamps already available or add them locally; keep existing log lines.
4. Tests: `test_recorder.py`: peak and frames survive `stop_recording`, zero frames reported, first-block warning path. `test_overlay_flow.py`: zero frames -> no transcribe call and the "Nothing was captured" toast; empty transcript with peak 0.0 -> "delivered silence"; empty transcript with peak > 0 -> unchanged toast; `FakeRecorder` without `last_take_stats` still works.

## Verify before reporting
Run: `env -u SSLKEYLOGFILE .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
Paste the output in your REPORT under PROOF.

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
