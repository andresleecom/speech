# Task 01: Test isolation, deflake, CI timeouts, version in startup log, non-blocking Intel dmg

You are the MAP executor (Grok CLI). Obey HARD RULES. No git. End with ## REPORT.

## Goal
pytest never writes into the real `%APPDATA%\Speech` again, the one sleep-based wake-word test is deterministic, every CI and release job has a timeout and a pip cache, the release build jobs stop running the test suite a second time, the startup log names the version and settings path, and a failure of the Intel macOS build no longer blocks publishing the other assets.

## Context - read these first
- `src/winwhisper/config.py` (`app_data_dir`, ~line 129): honours the `WINWHISPER_APPDATA_DIR` env var. This is the isolation hook.
- `src/winwhisper/logger.py` (`_setup_logging`): a module-level `_CONFIGURED` flag makes the RotatingFileHandler sticky for the process, so the env var must be set before the first `get_logger()` call in the test session.
- `tests/test_config.py` already sets `WINWHISPER_APPDATA_DIR` per test with monkeypatch; keep those tests working.
- `tests/test_wake_word.py` around line 445: `time.sleep(0.06)  # let the monitor see speech first` is the flaky wait. `StubDetector` records calls; poll on that instead of sleeping.
- `.github/workflows/ci.yml` and `.github/workflows/release.yml`: release jobs `linux`, `windows`, `macos` each run `python -m pytest -q` although `ci.yml` already gates main; the `macos` job matrix has an `intel` leg on `macos-15-intel`; `publish` needs all three and lists `Speech-*-intel.dmg*` assets explicitly (~lines 341-344).
- `src/winwhisper/main.py` ~line 1227-1235: the `Speech starting.` and `Settings loaded:` log lines. `winwhisper.__version__` exists (see `src/winwhisper/__init__.py`); `config.settings_path()` exists.
- `src/winwhisper/diagnostics.py`: prints OS and Python versions but not the app version.

## Scope - you may edit
- `tests/conftest.py` (new), `tests/test_wake_word.py`
- `.github/workflows/ci.yml`, `.github/workflows/release.yml`
- `src/winwhisper/main.py` (only the startup log lines), `src/winwhisper/diagnostics.py`, `src/winwhisper/logger.py` (only if a reset helper is needed for the fixture)

## Out of scope - do not touch
- Everything else under `src/`, `docs/`, `installer/`, `packaging/`, `pyproject.toml`, any other test file.

## Steps
1. `tests/conftest.py`: a session-scoped autouse fixture that sets `WINWHISPER_APPDATA_DIR` to `tmp_path_factory.mktemp("appdata")` before any `winwhisper` import happens in the session (use `pytest_configure` or import ordering so `logger._setup_logging` never sees the real dir). If a `winwhisper` logger was already configured, reset `logger._CONFIGURED` and close its handlers so the fixture's directory wins.
2. `tests/test_wake_word.py`: replace the `time.sleep(0.06)` with a deadline loop (max 2 s, 5 ms step) that waits until the stub detector has been called at least once, then continues as today.
3. `ci.yml`: `timeout-minutes: 20` on the test job; add `cache: pip` to `actions/setup-python`. `release.yml`: `timeout-minutes` on every job (prepare 10, builds 45, publish 15); `cache: pip` where `setup-python` is used; delete the `python -m pytest -q` steps from the three build jobs (CI already ran them on main).
4. `release.yml`: make the Intel leg non-blocking. Add `continue-on-error: ${{ matrix.architecture == 'intel' }}` on the `macos` job and make the `publish` job tolerate missing intel assets (upload only the files that exist; do not fail on absent `*-intel.dmg*`). Keep the Apple Silicon leg mandatory.
5. `main.py`: extend the `Speech starting.` line to `Speech %s starting (settings=%s).` with `__version__` and `settings_path()`. `diagnostics.py`: print `Speech version: <__version__>` as the first line.
6. Run the verify commands. Confirm `%APPDATA%\Speech\logs\app.log` does not gain new lines during the run: note its size before and after in PROOF.

## Verify before reporting
Run: `env -u SSLKEYLOGFILE .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
Run: `env -u SSLKEYLOGFILE .venv/Scripts/python.exe -m winwhisper.diagnostics | head -3`
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
