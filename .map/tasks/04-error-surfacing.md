# Task 04: Notification queue, Open Log Folder, version item, drop-only-bad-keys settings recovery

You are the MAP executor (Grok CLI). Obey HARD RULES. No git. End with ## REPORT.

## Goal
Every notification sent before the tray icon exists is delivered once the icon is visible, the tray offers "Open Log Folder" and shows the version, and a single invalid key in settings.json no longer resets every setting.

## Context - read these first
- `src/winwhisper/tray.py`: `run()` creates the pystray `Icon` (~line 41-55); `notify()` (~line 81-89) returns silently when `self._icon is None`; `_make_menu` (~line 94) builds the items; there is a `_ui_lock`.
- pystray: `Icon.run(setup=callable)` calls `setup(icon)` on the icon thread; Win32 balloon notifications need `icon.visible = True` first. Check `.venv/Lib/site-packages/pystray/_base.py` for the exact signature.
- `src/winwhisper/main.py`: `run()` (~line 152-220) sends several `self.notify(...)` calls before `self.tray.run()` at ~line 218, so they are lost today; `open_settings_file` (~line 726) and `_open_path` (~line 1414) show how to open a path with the OS; `winwhisper.__version__`.
- `src/winwhisper/config.py`: `load_settings()` (~line 160-185) quarantines the whole file on any `ValidationError` and returns defaults; `_quarantine_corrupt_settings`; `Settings` is a pydantic model with per-field validators.
- Tests: `tests/test_tray.py` (FakeIcon/FakeMenu pattern), `tests/test_config.py`, `tests/test_main.py`, `tests/test_overlay_flow.py` (FakeTray).

## Scope - you may edit
- `src/winwhisper/tray.py`, `src/winwhisper/main.py`, `src/winwhisper/config.py`
- `tests/test_tray.py`, `tests/test_config.py`, `tests/test_main.py`, `tests/test_overlay_flow.py`

## Out of scope - do not touch
- `recorder*.py`, `audio_inputs.py`, `transcriber.py`, `wake_word*.py`, overlay files, docs, installer, workflows, `pyproject.toml`.

## Steps
1. `tray.py`: while `_icon is None`, append `(title, message)` to a bounded queue (max 20) under `_ui_lock`. Pass `setup=` to `icon.run(...)`: it sets `icon.visible = True`, then drains the queue in order through the normal notify path. Keep `notify` non-blocking and safe from worker threads. Add a FakeIcon test that proves messages sent before `run()` arrive after it.
2. `tray.py` menu: add a disabled item `Speech <version>` at the top of the menu and an `Open Log Folder` item that calls a new controller method `open_log_folder()` which uses `_open_path(app_data_dir() / "logs")`. Keep the existing item order otherwise. Version comes from `winwhisper.__version__`.
3. `config.py`: add `load_settings_report() -> SettingsLoadReport` (dataclass: `settings: Settings`, `notices: list[str]`, `first_run: bool`). `first_run` is True when the file did not exist. On `ValidationError`: collect the offending top-level keys from `exc.errors()[i]["loc"][0]`, drop them from the data, retry (at most 3 rounds), add a notice `Settings key(s) ignored: a, b (restored defaults for them)`; keep the `.corrupt` backup only when the retry still fails or the JSON is unparsable, with notice `Settings could not be read; previous copy saved as settings.json.corrupt`. `load_settings()` keeps its signature and returns `load_settings_report().settings`.
4. `main.py`: the entry point uses `load_settings_report()`, passes `notices` to the controller, and the controller notifies each notice at the start of `run()` (they will be queued and delivered by the tray). Store `first_run` on the controller for the next task; do not act on it yet.
5. Tests: queue drained after setup; `Open Log Folder` calls `_open_path` with the logs dir; version item present; `load_settings_report` drops only the bad key (e.g. `custom_vocabulary: 5` keeps hotkeys and device intact); unparsable JSON still quarantines and reports; `first_run` True only when the file was absent.

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
