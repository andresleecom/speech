# Task 01: make the wake word hear "oye speech", gate on VAD, and stop only on a trailing stop phrase

You are the MAP executor. Obey HARD RULES. No git. End with ## REPORT.

## Goal
Hands-free dictation is a README headline and does not work in Spanish. Measured on the owner's probe clips with the tiny model: the current `detect_phrase` loop (auto pass, then each language hint) misses both "oye speech" clips on every pass, while a single pass with the phrases as `initial_prompt` ("Hey speech. Oye speech.") hits all three clips and costs about a third as much. Make detection one prompted pass, gate windows with the bundled Silero VAD, make the stop phrase fire only as the trailing phrase before a pause, and let the phrase choose the take's language.

## Context - read these first
- `src/winwhisper/wake_word.py`: constants (`SPEECH_LEVEL_THRESHOLD` is 0.01 after the 8x `boost_audio`, about -58 dBFS raw), `phrase_in_text` (1-edit fuzzy on any word of 4 or more letters, matches anywhere in the text), `WhisperPhraseDetector.detect_phrase` (loops over `[None, *languages]`), `_run_model` (`beam_size=1, vad_filter=True, language=...`), `WakeWordListener._detect_once` (RMS gate then `detect_phrase`), `StopWordMonitor._run` (RMS gate; silence is only counted when the whole 2.5 s tail is quiet).
- `src/winwhisper/main.py`: `_on_wake_word` (calls `toggle()` with no language override), the listener construction using `language_hints(...)`, `_start_wake_listener`, the stop monitor wiring (`stop_phrase`, `wake_silence_timeout_seconds`), the `trim_trailing_phrase` call.
- `src/winwhisper/config.py`: `wake_word_enabled`, `wake_phrases`, `stop_phrase`, `wake_silence_timeout_seconds`, `wake_model_size`, and the `_migrate_wake_phrase` pattern.
- faster-whisper facts: `model.transcribe(audio, beam_size=1, vad_filter=True, initial_prompt=..., condition_on_previous_text=False, temperature=0.0, compression_ratio_threshold=None, log_prob_threshold=None)`; `from faster_whisper.vad import get_speech_timestamps, VadOptions` returns speech segments for a float32 16 kHz array.
- Tests: `tests/test_wake_word.py` (StubDetector, FakeRecentRecorder, listener and monitor tests), `tests/test_overlay_flow.py`, `tests/test_config.py`.

## Scope - you may edit
- `src/winwhisper/wake_word.py`, `src/winwhisper/config.py`, `src/winwhisper/main.py`
- `tests/test_wake_word.py`, `tests/test_config.py`, `tests/test_overlay_flow.py`
- `docs/configuration.md` (wake-word section and settings table), `README.md` (hands-free paragraph)

## Out of scope - do not touch
- `wake_word_source*.py`, `recorder*.py`, `transcriber.py`, `tray.py`, everything else.

## Steps
1. `WhisperPhraseDetector`: `detect_phrase(audio, phrases) -> str | None` returns the matched phrase (not the transcript) after one pass with `initial_prompt` built from the phrases as capitalised sentences, `temperature=0.0`, `condition_on_previous_text=False`, and the fallback thresholds disabled; keep the CPU fallback. Keep accepting `languages` in the constructor but ignore it. Log every transcript that reaches the model at INFO as `Wake-word window heard %r`. Add `detect_transcript(audio, phrases) -> tuple[str | None, str]` if tests need the transcript as well.
2. VAD gate: add `has_speech(audio_int16) -> bool` using `get_speech_timestamps` on the boosted float audio with conservative `VadOptions` (minimum speech 250 ms); `_detect_once` runs the RMS gate first, then `has_speech`, then the model. `StopWordMonitor._run` records the time of the last VAD-detected speech in the tail and counts silence from it, so the timeout no longer needs a fully silent 2.5 s tail.
3. Stop phrase: `phrase_in_text` keeps 1-edit fuzziness only for words of 5 or more letters, so "stop" no longer matches "step" or "shop"; add `phrase_is_trailing(phrase, text)` and use it in the stop monitor, which evaluates the phrase only when the last ~0.5 s of the tail is below the RMS gate. The default `stop_phrase` stays "stop".
4. Per-phrase language: `Settings.wake_phrase_languages: dict[str, str]` defaulting to `{"hey speech": "en", "oye speech": "es"}` (normalised keys, validated language codes, unknown phrases allowed); the listener's `on_wake` callback receives the matched phrase; `main._on_wake_word(phrase)` looks up the override (absent means the configured mode) and calls `toggle(language_override=...)`. Remove the `language_hints` call from the listener construction.
5. Docs: `docs/configuration.md` documents `wake_phrase_languages`, the VAD gate, and that the stop phrase must be the last thing said before a pause; the README hands-free paragraph says the same in one sentence. One sentence per line, no em dashes.
6. Tests: prompted single pass (a fake model records `initial_prompt` and is called once); the matched phrase is returned; `has_speech` is patched in listener tests; the stop monitor fires on a transcript ending in the phrase after a pause and not on "stop the car now" nor on "step"; the silence timeout is counted from the last speech; `wake_phrase_languages` defaults, validation, and the override reaching `toggle`; existing tests are updated rather than deleted.

## Verify before reporting
Run: `env -u SSLKEYLOGFILE .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
Run (real clips, real tiny model), which must print `oye speech` for rounds 1 and 2 and `hey speech` for round 3:
`PYTHONUTF8=1 env -u SSLKEYLOGFILE .venv/Scripts/python.exe -c "import wave, numpy as np; from winwhisper.wake_word import WhisperPhraseDetector, boost_audio; d=WhisperPhraseDetector(); [print(n, d.detect_phrase(boost_audio(np.frombuffer(wave.open(f'probe_recordings/round_{n}.wav').readframes(64000), dtype=np.int16)), ['hey speech','oye speech'])) for n in (1,2,3)]"`
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
