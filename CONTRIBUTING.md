# Contributing to Speech

Thanks for improving Speech. Keep changes focused, add tests for behavior changes, and verify the platforms affected by your work.

## Development setup

Speech supports Python 3.11 and 3.12. Clone the repository and enter it:

```bash
git clone https://github.com/andresleecom/speech.git
cd speech
```

Create a virtual environment:

```powershell
# Windows PowerShell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS or Linux
python3.12 -m venv .venv
source .venv/bin/activate
```

Use the equivalent Python 3.11 command when needed.

On Debian or Ubuntu, install the native development and runtime dependencies first:

```bash
sudo apt install \
  build-essential \
  curl \
  file \
  gir1.2-ayatanaappindicator3-0.1 \
  gir1.2-gtk-3.0 \
  libcairo2-dev \
  libgirepository1.0-dev \
  libportaudio2 \
  pkg-config \
  python3-dev \
  xclip
```

If the environment uses a non-system Python, install its matching development headers. Then install the development requirements:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

## Run and test

Start the tray application from the activated environment:

```bash
python -m winwhisper.main
```

Run the full test suite:

```bash
python -m pytest -q
```

CI runs the tests on Windows, macOS, and Linux for every pull request.

## Diagnostics

Run the diagnostic report while investigating environment or device failures:

```bash
python -m winwhisper.diagnostics
```

It reports the platform, Python version, microphone inputs, model configuration, dependencies, API-key presence, and temporary directory checks.

## Packaging

Build the Windows application and installer with Inno Setup 6 installed:

```powershell
.\scripts\build_windows.ps1
```

Build both macOS application and DMG assets on a Mac:

```bash
bash scripts/build_macos.sh python
```

Build the Linux AppImage and Debian package on x86_64 Linux:

```bash
bash scripts/build_linux.sh python
```

Generated packages and checksums are written under `dist/installer`.

## Releases

Every push to `main` starts the release workflow. It tests all supported platforms, builds Windows, Apple Silicon macOS, Intel macOS, and Linux assets, verifies them, and publishes only after every job succeeds.

The version in `pyproject.toml` defines the release train. GitHub Actions adds the immutable workflow run number as a fourth component, such as `0.1.12.23`.

Change the base version only when starting a new major, minor, or patch train. Do not create release tags manually.

Each release publishes stable download names and matching versioned assets:

- `Speech-Setup.exe`
- `Speech.dmg`
- `Speech-intel.dmg`
- `Speech.AppImage`
- `Speech.deb`

## README media

The README GIFs are generated rather than screen-recorded. Regenerate them after changing the overlay or default shortcuts:

```bash
python scripts/make_demo_gif.py
python scripts/make_linux_gif.py
python scripts/make_hotkeys_gif.py
```

Commit the updated GIF and its generator change together.

## Pull requests

- Explain what changed and why.
- Keep unrelated changes out of the same pull request.
- Add or update tests for behavior changes.
- Run `python -m pytest -q` before requesting review.
- Update user documentation when behavior, requirements, or limitations change.

For vulnerabilities, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.
