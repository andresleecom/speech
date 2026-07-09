# Speech

[![CI](https://github.com/andresleecom/speech/actions/workflows/ci.yml/badge.svg)](https://github.com/andresleecom/speech/actions/workflows/ci.yml)
[![CodeQL](https://github.com/andresleecom/speech/actions/workflows/codeql.yml/badge.svg)](https://github.com/andresleecom/speech/actions/workflows/codeql.yml)
[![Latest release](https://img.shields.io/github/v/release/andresleecom/speech)](https://github.com/andresleecom/speech/releases/latest)
[![License: MIT](https://img.shields.io/github/license/andresleecom/speech)](LICENSE)
![Platforms](https://img.shields.io/badge/platforms-Windows%20%7C%20macOS-blue)

Speech is a Windows 10/11 and macOS tray app for local speech dictation.
It records your microphone with a global hotkey, transcribes with faster-whisper, optionally cleans the text, and pastes into the focused app.
It transcribes in 99 languages with automatic language detection, and has quick-force hotkeys for English and Spanish.

![Demo: press the hotkey, speak, and the text is pasted at your cursor](docs/demo.gif)

## How it works

1. Click where you want your words to go, in any app.
2. Press `Ctrl+Alt+Space` (`Ctrl+Option+Space` on a Mac) to start recording. A floating orb appears near your cursor.
3. Speak, then press the same combo again or click the red button to stop.
4. Speech transcribes locally and pastes the text right where your cursor was.

Speech remembers which window was active when you started recording and focuses it again before pasting, so the text lands where you were working even if you clicked elsewhere while speaking.

## Works in every app you type in

Speech types wherever your cursor is, so it works with virtually any Windows application.

- Browsers: Chrome, Edge, Firefox, and any web app running in them.
- Messaging: Slack, WhatsApp Desktop, Telegram, Discord, Teams.
- Email: Outlook, Gmail, Thunderbird.
- Notes and documents: Notepad, OneNote, Obsidian, Notion, Word.
- Coding: VS Code, JetBrains IDEs, Cursor, terminals, and coding agents such as Claude Code.

If you can type there, you can dictate there.
Speech pastes into the focused window with `Ctrl+V`, and automatically switches to `Ctrl+Shift+V` for terminal windows.

## Languages

In the default `auto` mode, Speech detects the language you speak and transcribes it in that language, covering the 99 languages of Whisper's multilingual models.
Dedicated hotkeys force English (`Ctrl+Alt+E`) or Spanish (`Ctrl+Alt+S`) for a single dictation when you want to skip detection.
You can also pin the language from the tray menu or with `language_mode` in the settings file.
Accuracy varies by language and model size: `small` is strong for widely spoken languages, and `medium` or `large-v3` improve the less common ones.
Text cleanup preserves the original language and never translates.

## Platform support

Windows 10/11 and macOS 12+ ship as downloadable apps.
Linux support is in development: the engine works on X11 from source, and the test suite runs on all three systems in CI (Wayland is not supported yet).

macOS notes:

- Global hotkeys need the Accessibility permission; macOS prompts on first use (System Settings > Privacy & Security > Accessibility > enable Speech).
- The hotkey combo uses the Option key where the docs say Alt (same key), and pasting uses `Cmd+V` automatically.
- Automatic in-app updates are Windows-only for now; download new DMGs from Releases.

## Installation for users

### Windows

Download the latest Windows installer from this repository's latest release:

```text
https://github.com/andresleecom/speech/releases/latest/download/Speech-Setup.exe
```

Run `Speech-Setup.exe`. The installer is per-user and does not require
administrator privileges. Versioned installers are also attached to each release
as `Speech-Setup-<version>.exe`.

The app checks GitHub Releases for updates once per day by default. When a new
version is available, use the tray menu item `Check for Updates` to confirm,
download, verify, and launch the installer.

### macOS

Pick the DMG that matches your Mac's chip (check under ` > About This Mac`):

| Your Mac | Download |
| --- | --- |
| Apple Silicon (M1 and later) | `https://github.com/andresleecom/speech/releases/latest/download/Speech.dmg` |
| Intel | `Speech-<version>-intel.dmg` from the [latest release](https://github.com/andresleecom/speech/releases/latest) |

Downloading the wrong architecture makes macOS refuse to open the app with an "incorrect executable format" or "Launch failed" error.

Then:

1. Open the DMG and drag `Speech.app` into `Applications`.
2. First launch: right-click `Speech.app`, choose `Open`, and confirm (the app is not yet code-signed).
3. Speech asks for the Accessibility permission - enable Speech in the list, then quit Speech (menu bar icon > Exit) and open it again. Both the global hotkey and automatic pasting need this permission.
4. Allow the Microphone permission on your first recording.

Speech lives in the menu bar (no Dock icon); the icon color shows the recording state.

## Development setup

Clone the repository.

```powershell
git clone https://github.com/andresleecom/speech.git
cd speech
```

Create a Python 3.11 or 3.12 virtual environment.

```powershell
py -3.12 -m venv .venv
```

Use `py -3.11 -m venv .venv` instead if you want Python 3.11.
Activate the virtual environment.

```powershell
.\.venv\Scripts\Activate.ps1
```

Upgrade pip.

```powershell
python -m pip install --upgrade pip
```

Install the runtime requirements.

```powershell
pip install -r requirements.txt
```

The requirements file installs the local package in editable mode and pulls the
runtime dependencies declared in `pyproject.toml`.

## Run

Start the tray app from the activated virtual environment.

```powershell
python -m winwhisper.main
```

## Using Speech on Windows

Open Notepad and click into it.
Press `Ctrl+Alt+Space`.
Say, "Hello this is a test."
Press `Ctrl+Alt+Space` again, or click the floating red recording button.
The transcribed text pastes into Notepad at your cursor.

To force Spanish for one dictation, use `Ctrl+Alt+S` to start and stop instead (`Ctrl+Alt+E` forces English).

## Using Speech on macOS

On a Mac keyboard, Alt is the Option key, so the combos below use `Control (^) + Option (⌥)`.

Open Notes and click into a note.
Press `Ctrl+Option+Space`.
Say, "Hello this is a test."
Press `Ctrl+Option+Space` again, or click the floating red recording button.
The transcribed text pastes into Notes at your cursor via `Cmd+V`, sent automatically.

If nothing happens when you press the hotkey, or the text stays on the clipboard without pasting, the Accessibility permission is missing: enable Speech under System Settings > Privacy & Security > Accessibility and relaunch the app.
Both symptoms come from that one permission - macOS requires it for listening to hotkeys and for sending the paste keystroke.

## Hotkeys table

| Action | Windows | macOS |
| --- | --- | --- |
| Start or stop recording | `Ctrl+Alt+Space` | `Ctrl+Option+Space` |
| Start or stop with English for this dictation | `Ctrl+Alt+E` | `Ctrl+Option+E` |
| Start or stop with Spanish for this dictation | `Ctrl+Alt+S` | `Ctrl+Option+S` |

## Customizing hotkeys

Edit the `hotkeys` object in `%APPDATA%\Speech\settings.json`, then restart Speech.

```json
"hotkeys": {
  "toggle_recording": "<ctrl>+<shift>+<numpad_plus>"
}
```

A combo is zero or more modifiers plus exactly one trigger key.
Supported modifiers are `<ctrl>`, `<alt>`, `<shift>`, and `<cmd>` (the Windows key).
The trigger can be a letter or digit, a function key such as `<f8>`, or a named key such as `<space>`, `<numpad_plus>`, `<numpad_minus>`, `<numpad0>` through `<numpad9>`, `<plus>`, or `<minus>`.
Remove an action from `hotkeys` to leave it without a hotkey.
If a combo is already registered by another application, Speech logs a warning and skips it.

On Spanish and other international layouts, `Ctrl+Alt` is the same key as `AltGr`.
That makes the default `Ctrl+Alt+E` fire when you type `€` with `AltGr+E`, and `Ctrl+Alt+S` when you type `AltGr+S`.
If that gets in your way, rebind those actions to combos without `Ctrl+Alt`, or use a numpad key such as `<ctrl>+<shift>+<numpad_plus>`, which never collides with typing.

## Settings file location and keys

The settings file is `%APPDATA%\Speech\settings.json`.
The app creates the file on first run if it does not exist.

| Key | Default | Description |
| --- | --- | --- |
| `model_size` | `small` | faster-whisper model size. |
| `device` | `cpu` | Inference device such as `cpu` or `cuda`. |
| `compute_type` | `int8` | faster-whisper compute type. |
| `language_mode` | `auto` | Use `auto`, `en`, or `es`. |
| `cleanup_mode` | `basic` | Use `none`, `basic`, or `llm`. |
| `paste_mode` | `auto` | Paste shortcut mode. `auto` uses `Ctrl+Shift+V` for common terminal windows and `Ctrl+V` elsewhere. Older `clipboard_ctrl_v` settings keep the same terminal detection. Use `clipboard_ctrl_shift_v` to force `Ctrl+Shift+V`. |
| `delete_audio_after_transcription` | `true` | Delete temporary WAV files after transcription. |
| `check_for_updates` | `true` | Check GitHub Releases for updates at most once per day. |
| `last_update_check_at` | `null` | Internal timestamp for update throttling. |
| `hotkeys` | See defaults above. | Global hotkey bindings. |
| `custom_vocabulary` | `[]` | Names and terms you use often, transcribed with these exact spellings. |

Language and cleanup mode can be changed from the tray menu without a restart.
After editing `hotkeys`, `model_size`, `device`, `compute_type`, or
`custom_vocabulary` in the settings file, restart Speech for those values to
take effect.

## Custom vocabulary

Whisper guesses unfamiliar names and jargon phonetically, so "README" can come out as "Rhythmi" and product names get mangled.
List the words you use often in `custom_vocabulary` and Speech biases both transcription and LLM cleanup toward those exact spellings.

```json
"custom_vocabulary": ["README", "Claude Code", "winwhisper", "Andres Lee"]
```

Good candidates are product names, people's names, company jargon, and technical terms.
Keep the list short and specific; a few dozen entries work better than hundreds.
Restart Speech after editing it.

## Floating recording button

When recording starts, Speech shows a floating circular recording
orb to the right of the text cursor when Windows exposes it, or near the mouse
cursor as a fallback. The red center button stops recording, and the surrounding
sonar rings pulse while the microphone is live. Drag the orb to move it. After
you stop recording, the orb switches to a transcribing spinner until the text is
ready. The app remembers the active window from the start of recording and tries
to focus it again before pasting, so the text goes back where your cursor was
when dictation began.

On Windows, the overlay uses a native layered window with per-pixel alpha for
smooth circular edges and transparent corners. Tkinter is kept as a fallback for
development and future non-Windows work.

In `auto` paste mode, terminal windows such as Windows Terminal, WezTerm,
Alacritty, mintty, and legacy console hosts receive `Ctrl+Shift+V`. Other
windows receive `Ctrl+V`.

## Model Recommendations

Use `small` on `cpu` with `int8` for the default MVP experience.
Use `medium` if you want better accuracy and can accept slower transcription.
Use `large-v3` if you want the highest accuracy and have enough memory and patience.
Use `cuda` with `float16` or `int8_float16` when you have a supported NVIDIA GPU.

## Security and privacy

Speech is built so you do not have to take anyone's word for it - the code is open and every claim below can be checked in the source.

**Your voice never leaves your machine.**
Recording and transcription run entirely locally with faster-whisper; there is no cloud speech service, no account, and no telemetry or analytics of any kind.
Temporary WAV files are written under the app's temp folder and deleted after transcription by default (`delete_audio_after_transcription`).
Logs never contain your dictated text.

**The app makes exactly three kinds of network connections, all inspectable in the source:**

1. Downloading the Whisper model from Hugging Face on first run (or when you change `model_size`).
2. A daily update check against this repository's GitHub Releases (Windows only; disable with `"check_for_updates": false`).
3. Optional LLM text cleanup via the OpenAI API - only if you set `cleanup_mode` to `llm` **and** provide your own `OPENAI_API_KEY`; it is off by default, and then only the transcribed text (never audio) is sent.

Nothing else talks to the network.

**Supply-chain and code checks:**

- The full source is MIT-licensed in this repository; the installers are built from it by the public GitHub Actions [release workflow](.github/workflows/release.yml), so you can trace any release to its exact commit.
- [CodeQL](https://github.com/andresleecom/speech/security/code-scanning) scans every pull request and runs weekly.
- The test suite runs on Windows, macOS, and Linux in [CI](https://github.com/andresleecom/speech/actions/workflows/ci.yml) for every change.
- CI runs with least-privilege permissions; only the release workflow can write, and only to Releases.

**Verify your download.**
Every release asset ships with a `.sha256` checksum file.

```powershell
# Windows
certutil -hashfile Speech-Setup-<version>.exe SHA256
```

```bash
# macOS
shasum -a 256 Speech-<version>.dmg
```

Compare the output to the matching `.sha256` asset on the release page.
The binaries are not yet code-signed (Windows SmartScreen and macOS Gatekeeper will warn); checksum verification plus the auditable build pipeline is the current chain of trust, and code signing is on the roadmap.

Found a vulnerability? Please report it privately - see [SECURITY.md](SECURITY.md).

## Diagnostics

Run diagnostics from the activated virtual environment.

```powershell
python -m winwhisper.diagnostics
```

The diagnostics report includes Python, OS, microphone, model, dependency, API key presence, and temp directory checks.

## Known limitations

Dictation text remains on the clipboard after each paste attempt so you can press
`Ctrl+V` manually if the focused app did not accept the automatic paste.
Previous clipboard content is not preserved in the MVP.

## Troubleshooting

Some antivirus products that intercept TLS, such as Norton, break the first-run model download in two ways.
They set `SSLKEYLOGFILE` to a special device path, which crashes OpenSSL with a "no OPENSSL_Applink" error.
They also re-sign HTTPS traffic with a certificate that Python's default trust store rejects, causing `CERTIFICATE_VERIFY_FAILED`.
The app works around both automatically at startup: it removes an invalid `SSLKEYLOGFILE` value and trusts the Windows certificate store via `truststore`.
If you download models from your own scripts instead, apply the same two workarounds there.

## Packaging and releases

Install development dependencies.

```powershell
pip install -r requirements-dev.txt
```

Install Inno Setup 6, then build the Windows app and installer.

```powershell
.\scripts\build_windows.ps1
```

The build outputs:

- `dist\Speech\Speech.exe`
- `dist\installer\Speech-Setup-<version>.exe`
- `dist\installer\Speech-Setup-<version>.exe.sha256`
- `dist\installer\Speech-Setup.exe`
- `dist\installer\Speech-Setup.exe.sha256`

To publish a release, update the version in `pyproject.toml`, then push a tag
such as `v0.1.0`. The GitHub Actions release workflow builds the installer and
publishes both the stable installer URL and the versioned `.exe` plus `.sha256`
files to GitHub Releases.

The README demo GIF is generated, not screen-recorded.
Regenerate `docs/demo.gif` after visual changes to the overlay.

```powershell
python scripts\make_demo_gif.py
```

## Roadmap

- Windows installer and GitHub Releases auto-update: current target.
- macOS app bundle and signed/notarized installer.
- Linux AppImage or distro packages.
