# Task 01 follow-up: tolerate a one-letter slip in a short wake word when the rest matches exactly

You are the MAP executor. Obey HARD RULES. No git. End with ## REPORT.

## Goal
Real-audio check: a synthesized Spanish voice saying "oye speech" was transcribed as "Oje speech." and missed, because words shorter than five letters must match exactly. For wake phrases of two or more words, allow a 1-edit slip in a word of three or four letters when at least one other word of the phrase matches exactly. The stop phrase keeps the strict rule (a single short word such as "stop" must match exactly). Do not redo the rest of task 01.

## Context - read these first
- `src/winwhisper/wake_word.py`: `_words_match_fuzzy`, `phrase_in_text`, `phrase_is_trailing`, `WhisperPhraseDetector.detect_transcript` (calls `phrase_in_text` for wake phrases), `StopWordMonitor._run` (calls `phrase_is_trailing`).
- `tests/test_wake_word.py`: the `phrase_in_text` and stop-phrase tests.

## Scope - you may edit
- `src/winwhisper/wake_word.py`, `tests/test_wake_word.py`

## Out of scope - do not touch
- Everything else.

## Steps
1. Give `phrase_in_text` a keyword `allow_short_slip: bool = False`. When true and the phrase has two or more words, a candidate window matches if every word matches with the existing rule or is within 1 edit for words of three or four letters, provided at least one word in the window matches exactly. `detect_transcript` passes `allow_short_slip=True` for wake phrases only. `phrase_is_trailing` and the stop path are unchanged.
2. Tests: "Oje speech." matches "oye speech"; "hey speach" still matches; "hay speech" matches (accepted trade-off, documented in the test); "oje spich" does not (no exact word); the stop phrase "stop" still does not match "step" or "shop" and only fires trailing.

## Verify before reporting
Run: `env -u SSLKEYLOGFILE .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_wake_word.py`
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
