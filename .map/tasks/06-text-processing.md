# Task 06: Text processing fixes and version 0.1.21

You are the MAP executor (Grok CLI). Obey HARD RULES. No git. End with ## REPORT.

## Goal
Basic cleanup stops capitalizing the wrong character (`3 apples` becomes `3 Apples` today), consecutive takes stop gluing together (`frase.Frase`), users can opt into spoken newline commands in English and Spanish, and Whisper's stock hallucinations are discarded instead of pasted. The version becomes 0.1.21.

## Context - read these first
- `src/winwhisper/formatter.py` (90 lines): `clean_text`, `_basic_cleanup`, `_uppercase_first_alphabetic` (uppercases the first alphabetic character anywhere), `_llm_cleanup`.
- `src/winwhisper/main.py` `_stop_and_process`: `clean_text(...)` (~line 1215), `trim_trailing_phrase` (~line 1223), the empty check `if not cleaned.strip()` (~line 1225) and `_notify_empty_transcription`.
- `src/winwhisper/config.py`: `cleanup_mode: Literal["none", "basic", "llm"]`, other boolean settings for the validator pattern.
- `tests/test_formatter.py` (nine exact-string tests), `tests/test_overlay_flow.py` (controller harness with a fake transcriber), `tests/test_config.py`, `tests/test_main.py` (the version test is format-based).
- Log evidence: 35% of pastes land within 60 s of the previous one; the wake path has produced `Subtítulos por la comunidad de Amara.org` and `Thank you for watching!` on noise.

## Scope - you may edit
- `src/winwhisper/formatter.py`, `src/winwhisper/main.py`, `src/winwhisper/config.py`, `pyproject.toml`
- `tests/test_formatter.py`, `tests/test_overlay_flow.py`, `tests/test_config.py`
- `README.md` (Customize table, Cleanup row only), `docs/configuration.md` (Text cleanup section and settings table)

## Out of scope - do not touch
- `transcriber.py`, `tray.py`, `wake_word*.py`, everything else. No spoken period/comma tables, no filler-word removal, no per-favorite profiles.

## Steps
1. `formatter.py`: `_uppercase_first_alphabetic` uppercases the first alphabetic character only when it is at index 0 or preceded solely by opening punctuation (`¿ ¡ ( [ { " ' « “ ‘`); `3 apples`, `e.g. foo` and `git status` stay as they are; `¿qué` becomes `¿Qué`; `hola` becomes `Hola`.
2. `config.py`: `append_trailing_space: bool = True` and `newline_commands: bool = False` with boolean validators like the existing ones.
3. `formatter.py`: `clean_text(text, mode, vocabulary=None, *, append_trailing_space=False, newline_commands=False)`. For modes `basic` and `llm`: when `newline_commands` is on, replace the standalone phrases `new line`, `new paragraph`, `nueva línea`, `punto y aparte` (case-insensitive, optional surrounding punctuation and spaces) with `\n` and `\n\n` before capitalization; when `append_trailing_space` is on and the result ends in `.`, `!`, `?` or `…`, append one space. Mode `none` returns the text unchanged.
4. `main.py`: pass the two settings into `clean_text`; after the empty check add a whole-text blocklist: normalize (casefold, strip punctuation and spaces) and discard when the text equals one of `thank you for watching`, `thanks for watching`, `gracias por ver`, `subtítulos por la comunidad de amara.org`, `subtítulos realizados por la comunidad de amara.org`, or contains `amara.org`; treat it like an empty transcription with the log line `Discarded stock phrase.`. The trailing space must be appended after `trim_trailing_phrase`, never before the empty check.
5. Docs: `docs/configuration.md` Text cleanup section and settings table document both keys and the blocklist; README Cleanup row mentions trailing spacing and optional newline commands. `pyproject.toml` version `0.1.21`. One sentence per line, no em dashes.
6. Tests: the capitalization cases above; trailing space on and off, and never in mode `none`; newline commands in both languages and off by default; a controller test where the fake transcriber returns `Thank you for watching.` and nothing is pasted; settings defaults.

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
