# MAP: hands-free wake word that actually hears "oye speech"

**Goal:** "hey speech" and "oye speech" wake the app reliably with one model pass per poll, the stop phrase fires only when spoken as the last words before a pause, and the language of the take follows the phrase that woke it.
**Base:** main @ 592bda9 (0.1.22) · **Branch:** map/hands-free · **Tier:** M (diagnosis done: the probe clips reproduce the miss)
**Non-goals:** OpenWakeWord or Porcupine, streaming preview, a wake-word settings UI.

## Decisions
- D01 Orchestrator = fable-5; executor primary = grok-4.5, fallback codex gpt-5.6-sol, then Opus.
- D02 Measured on the owner's probe clips (tiny, CPU int8): the auto, es, and en passes miss both "oye speech" clips; one pass with the phrases as `initial_prompt` hits all three clips in 350-450 ms versus about 500 ms per pass today. Detection becomes a single prompted pass; the language-hint loop goes away and the `languages` constructor argument is accepted but ignored for one release.
- D03 Gates: keep the cheap RMS pre-filter, then require speech from `faster_whisper.vad.get_speech_timestamps` on the window before calling the model; the stop monitor counts silence from the last VAD-detected speech instead of requiring a fully silent 2.5 s tail.
- D04 Stop phrase: exact match, with 1-edit fuzziness only for words of 5 or more letters, only when it is the trailing phrase of the transcript and the last ~0.5 s of the tail is below the gate. The default stays "stop" so documented behaviour holds.
- D05 The detector returns the matched phrase; `wake_phrase_languages` maps a phrase to a language code (defaults: hey speech = en, oye speech = es; absent = configured mode) and the wake path calls `toggle(language_override=...)`.
- D06 Every wake-window transcript that passes the gates is logged at INFO for one release of dogfooding.
- D07 Verification: unit tests with a fake model, plus the orchestrator drives the real detector, listener, and stop monitor with the three probe clips and synthesized speech; Andres does live takes after merge.

## Constraints
- No new dependencies (faster-whisper bundles Silero VAD). Run Python as `env -u SSLKEYLOGFILE .venv/Scripts/python.exe`. Markdown: one sentence per line, no em dashes.

## Verify commands
- tests: `env -u SSLKEYLOGFILE .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`

## Tasks
| # | Task | Scope (files/areas) | Bar | Status |
|---|------|---------------------|-----|--------|
| 01 | Prompted single-pass detection, VAD gates, trailing stop phrase, per-phrase language, dogfood logging | src/winwhisper/wake_word.py, config.py, main.py, tests/test_wake_word.py, test_config.py, test_overlay_flow.py, docs/configuration.md, README.md | build+tests+flow | pending |
