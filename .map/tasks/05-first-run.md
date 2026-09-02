# Task 05: First run: hotkey in the tray, model download toast, offline message, lenient model_size, Windows start at login, version bump

You are the MAP executor (Grok CLI). Obey HARD RULES. No git. End with ## REPORT.

## Goal
A new Windows user learns the dictation hotkey from the tray, sees that the speech model is downloading (with its size) instead of a silent stall, gets a specific message when the download cannot happen offline, can start Speech at login, and the release version becomes 0.1.19.

## Context - read these first
- `src/winwhisper/hotkey_settings.py`: `display_hotkey(combo, platform=...)` renders a trigger for humans. `src/winwhisper/hotkey_actions.py`: default hotkeys per platform.
- `src/winwhisper/tray.py`: `_make_menu` item `Start/Stop Recording` (~line 96); `set_status` tooltip; task 04 added the notification queue and `set_microphone_label`.
- `src/winwhisper/main.py`: `_warm_model_worker` (~line 949) preloads the model silently; `_stop_and_process` maps every load failure to `Dictation failed.` (~line 1050); the controller stores `first_run` from task 04's `load_settings_report()`; `run()` sends startup notices.
- `src/winwhisper/transcriber.py`: `_load_model` (~line 170) calls `WhisperModel(...)` at two sites (primary and CPU fallback). `faster_whisper.utils._MODELS` maps size names to Hugging Face repo ids. `huggingface_hub.try_to_load_from_cache(repo_id, "model.bin")` returns a path when cached and `None` otherwise (guard the import). Offline load raises `huggingface_hub` errors whose class names include `LocalEntryNotFoundError`; connection failures surface as `ConnectionError`/`ConnectError`.
- `src/winwhisper/config.py`: `model_size: str = "small"` has no validator; `_migrate_device` shows the lenient-migration pattern.
- `installer/Speech.iss`: has `[Setup]`, `[Files]`, `[Icons]`, `[Run]`, `[Code]`; no `[Tasks]` or `[Registry]`. `tests/test_windows_installer.py` asserts on its text.
- `pyproject.toml` `version = "0.1.18"`; `README.md` model row (~line 81) and `docs/configuration.md` model table (~line 120) list only small, medium, large-v3.

## Scope - you may edit
- `src/winwhisper/main.py`, `tray.py`, `config.py`, `transcriber.py`, `hotkey_actions.py`, new `src/winwhisper/startup.py`
- `installer/Speech.iss`, `pyproject.toml`, `README.md`, `docs/configuration.md`
- `tests/` (new `tests/test_startup.py`; extend `test_tray.py`, `test_overlay_flow.py`, `test_main.py`, `test_config.py`, `test_transcriber_device.py`, `test_windows_installer.py`)

## Out of scope - do not touch
- `recorder*.py`, `audio_inputs.py`, `wake_word*.py`, overlay files, `updater*.py`, workflows, `packaging/`.

## Steps
1. Tray: label the toggle item `Start/Stop Recording (<hotkey>)` using `display_hotkey` on the current toggle binding, refreshed when hotkeys change; tooltip keeps the microphone label from task 04 and adds the hotkey when idle. Add a Windows-only check item `Start at login` backed by `startup.py`.
2. `startup.py`: `is_enabled()`, `enable(exe_path)`, `disable()` using `winreg` on `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, value name `Speech`, quoted path to `sys.executable` when frozen; no-ops returning False on other platforms. Never write the key automatically; only from the tray item.
3. First-run toast: when `first_run` is True, at the start of `run()` notify `Press <hotkey> to dictate. The speech model (<size>, <MB> MB) downloads once. Microphone > Test Microphone checks your mic.` (macOS/Linux use their platform hotkey text).
4. `transcriber.py`: add `MODEL_DOWNLOAD_SIZES_MB = {"tiny": 75, "base": 145, "small": 464, "medium": 1530, "large-v3": 3090, "large-v3-turbo": 1620}`, `is_model_cached(model_size) -> bool | None` (None when the probe is unavailable), and `ModelDownloadError(TranscriptionError-or-the-existing-base)` raised from `_load_model` when the failure is an offline/no-cache error, with message `The speech model <size> needs a one-time download (<MB> MB). Connect to the internet and try again.`
5. `main.py`: before `ensure_model_loaded()` in `_warm_model_worker`, if `is_model_cached()` is False notify `Downloading speech model <size> (<MB> MB). The first dictation may take a minute.` and set the tray tooltip to `Downloading model...` until the load finishes; in `_stop_and_process` map `ModelDownloadError` to its own message instead of `Dictation failed.`.
6. `config.py`: lenient `model_size` validator: strip, empty -> `small`, otherwise accept any string; a `_migrate_model_size` that logs a warning for unknown names but keeps them. Also wrap the `_migrate_*` calls in `load_settings_report` in a `try/except (ValueError, TypeError)` that quarantines the file and returns the corrupt notice, since task 04 moved them outside the original try block.
7. Installer: `[Tasks]` entry `startup` ("Start Speech when you sign in", `Flags: checkedonce`) and a `[Registry]` HKCU Run value with `Flags: uninsdeletevalue; Tasks: startup`. Extend `test_windows_installer.py`.
8. Docs: README model row and `docs/configuration.md` model table add `large-v3-turbo` with sizes; README first-run note states the small model is about 464 MB. `pyproject.toml` version `0.1.19`. One sentence per line in Markdown, no em dashes.
9. Tests for: toggle label contains the display hotkey; first-run toast only when `first_run`; download toast only when the probe returns False; `ModelDownloadError` mapped to its message; `startup.py` with a fake winreg; lenient model_size.

## Verify before reporting
Run: `env -u SSLKEYLOGFILE .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
Run: `env -u SSLKEYLOGFILE .venv/Scripts/python.exe -c "from winwhisper.transcriber import is_model_cached; print(is_model_cached('small'), is_model_cached('large-v3-turbo'))"`
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
