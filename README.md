# Speech

[![Latest release](https://img.shields.io/github/v/release/andresleecom/speech)](https://github.com/andresleecom/speech/releases/latest)
[![CI](https://github.com/andresleecom/speech/actions/workflows/ci.yml/badge.svg)](https://github.com/andresleecom/speech/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/github/license/andresleecom/speech)](LICENSE)

**Local dictation that pastes wherever you type.**

Press a hotkey, speak, and Speech transcribes on-device in 100 languages. Your voice stays on your computer. No account, subscription, or cloud speech service required.

Windows 10/11 · macOS · Linux (x86_64, X11)

[Download the latest release](https://github.com/andresleecom/speech/releases/latest) · [How it works](#how-it-works) · [Privacy](#privacy)

![Speech dictation demo: press a hotkey, speak, and the transcription appears at the cursor](docs/demo.gif)

## Why Speech

- **Private by design.** Recording and transcription run locally with faster-whisper.
- **Works where you work.** Dictate into browsers, documents, chat apps, IDEs, and terminals.
- **Speaks your language.** Use automatic detection or choose from 100 supported languages.
- **Fits your workflow.** Pick a microphone, pin three language favorites, customize hotkeys, and choose your cleanup level.

## Download

Choose a package from the [latest release](https://github.com/andresleecom/speech/releases/latest):

| Platform | Package | Requirements |
| --- | --- | --- |
| Windows | [Speech-Setup.exe](https://github.com/andresleecom/speech/releases/latest/download/Speech-Setup.exe) | Windows 10 or 11 |
| macOS | [Apple Silicon DMG](https://github.com/andresleecom/speech/releases/latest/download/Speech.dmg) | M1 or newer |
| macOS | [Intel DMG](https://github.com/andresleecom/speech/releases/latest/download/Speech-intel.dmg) | Intel Mac |
| Linux | [AppImage](https://github.com/andresleecom/speech/releases/latest/download/Speech.AppImage) | x86_64, X11, FUSE |
| Debian/Ubuntu | [Debian package](https://github.com/andresleecom/speech/releases/latest/download/Speech.deb) | Ubuntu 22.04+ or Debian 12+, x86_64, X11 |

The binaries are not yet code-signed. Windows SmartScreen and macOS Gatekeeper may warn on first launch. Every release includes SHA-256 checksums and is built by the public [release workflow](.github/workflows/release.yml).

Before your first dictation:

- **Windows:** run the per-user installer. It does not require administrator privileges.
- **macOS:** right-click Speech, choose **Open**, then enable Microphone, Accessibility, and Input Monitoring permissions. Quit and reopen Speech after granting them.
- **Linux:** use an X11 session and an AppIndicator-compatible tray. Wayland is not supported yet. AppImage users may need `fuse3` and `libfuse2`.

The selected Whisper model downloads from Hugging Face on first use. Windows can check for updates inside the app; macOS and Linux updates are installed manually from Releases.

## How it works

1. Click where you want the text to appear.
2. Press the recording hotkey.
3. Speak, then press the same hotkey or click the red orb.
4. Speech transcribes locally, restores the original window, and pastes at the cursor.

| Action | Windows | macOS | Linux |
| --- | --- | --- | --- |
| Start or stop | `Ctrl+Alt+Space` | `Control+Option+Space` | `Ctrl+Alt+Space` |
| Favorite 1 | `Ctrl+Shift+E` | `Control+Shift+E` | `Ctrl+Shift+E` |
| Favorite 2 | `Ctrl+Shift+S` | `Control+Shift+S` | `Ctrl+Shift+S` |
| Favorite 3 | Disabled | Disabled | Disabled |

Favorites 1 and 2 default to English and Spanish. Assign any supported language to them from **Language Settings...** without changing the shortcuts.

![Speech dictation on Linux/X11: press Ctrl+Alt+Space, speak, and the transcription appears at the cursor](docs/linux.gif)

## Customize

Most settings are available from the tray or menu-bar icon and apply without a restart.

| Setting | What you can change |
| --- | --- |
| Microphone | Follow the system default or select a specific input; test it with the live recording orb. |
| Languages | Use automatic detection, select one language, or pin three favorites for quick dictation. |
| Cleanup | Keep raw transcription, apply local basic cleanup, or opt into LLM cleanup with your own OpenAI API key. |
| Hotkeys | Choose suggested shortcuts or enter custom combinations with duplicate and conflict validation. |
| Vocabulary | Bias transcription toward names, products, and technical terms you use often. |
| Model | Trade speed for accuracy with `small`, `medium`, or `large-v3`; supported NVIDIA GPUs can use CUDA. |

See [Configuration](docs/configuration.md) for settings paths, every key, hotkey syntax, model choices, and cleanup behavior.

## Privacy

Your microphone audio and Whisper transcription stay on your machine. Speech has no account system, telemetry, analytics, or transcript logging.

Speech makes only these network connections:

| Connection | When it happens | Data sent |
| --- | --- | --- |
| Hugging Face | The first time you use a Whisper model | Model download request |
| GitHub Releases | Daily on Windows, unless disabled | Update request; no dictated text |
| OpenAI API | Only when you enable LLM cleanup and provide a key | Transcript text, never audio |

Temporary WAV files are deleted after transcription by default. LLM cleanup is off by default and falls back to local basic cleanup if the request fails.

Releases are built from this repository in public GitHub Actions, scanned with CodeQL, tested on Windows, macOS, and Linux, and published with checksums. Report vulnerabilities through [SECURITY.md](SECURITY.md).

## Limitations and help

- Linux support requires X11; Wayland is not supported yet.
- A recording stops after 10 minutes to prevent unbounded memory use.
- Dictated text remains on the clipboard after pasting; the previous clipboard value is not restored.
- Unsigned Windows and macOS builds can trigger operating-system warnings.

Run `python -m winwhisper.diagnostics` from a development environment to inspect the OS, microphone, model, dependencies, API-key presence, and temporary directory.

See [Troubleshooting](docs/troubleshooting.md) for macOS permissions, Linux tray requirements, LLM cleanup, model downloads, and diagnostic steps. For bugs, open a [GitHub issue](https://github.com/andresleecom/speech/issues).

## Development

Speech requires Python 3.11 or newer.

```bash
git clone https://github.com/andresleecom/speech.git
cd speech
python -m venv .venv
# Activate .venv for your shell, then:
python -m pip install -r requirements-dev.txt
python -m winwhisper.main
```

Run the test suite with `python -m pytest -q`. Platform dependencies, environment activation, packaging commands, and release details live in [CONTRIBUTING.md](CONTRIBUTING.md).

## Roadmap

- Sign and notarize releases, then add native macOS updates.
- Support configurable or streamed long recordings.
- Add post-dictation controls and optional local-only history.
- Add push-to-talk and voice-activity modes.
- Improve model download and storage management.
- Add Wayland support without reducing X11 support.

Contributions are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md) or browse the [open issues](https://github.com/andresleecom/speech/issues).
