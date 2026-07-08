# WinWhisperDictate

WinWhisperDictate is a Windows 10/11 tray app for local speech dictation.
It records your microphone with a global hotkey, transcribes with faster-whisper, optionally cleans the text, and pastes into the focused app.
It supports English, Spanish, or automatic language detection.

## Installation

Clone the repository.

```powershell
git clone <repo-url>
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

Install the package in editable mode.

```powershell
pip install -e .
```

The editable install is required so `python -m winwhisper.main` resolves the `src` layout.

## Run

Start the tray app from the activated virtual environment.

```powershell
python -m winwhisper.main
```

## First Test

Open Notepad.
Press `Ctrl+Alt+Space`.
Say, "Hello this is a test."
Press `Ctrl+Alt+Space` again.
The transcribed text should paste into Notepad.

## Spanish Test

Open Notepad.
Press `Ctrl+Alt+S`.
Say, "Hola este es un mensaje de prueba."
Press `Ctrl+Alt+S` again.
The Spanish transcription should paste into Notepad.

## Hotkeys table

| Action | Default hotkey |
| --- | --- |
| Start or stop recording | `Ctrl+Alt+Space` |
| Start or stop with English for this dictation | `Ctrl+Alt+E` |
| Start or stop with Spanish for this dictation | `Ctrl+Alt+S` |

## Settings file location and keys

The settings file is `%APPDATA%\WinWhisperDictate\settings.json`.
The app creates the file on first run if it does not exist.

| Key | Default | Description |
| --- | --- | --- |
| `model_size` | `small` | faster-whisper model size. |
| `device` | `cpu` | Inference device such as `cpu` or `cuda`. |
| `compute_type` | `int8` | faster-whisper compute type. |
| `language_mode` | `auto` | Use `auto`, `en`, or `es`. |
| `cleanup_mode` | `basic` | Use `none`, `basic`, or `llm`. |
| `paste_mode` | `clipboard_ctrl_v` | Clipboard paste mode for the MVP. |
| `delete_audio_after_transcription` | `true` | Delete temporary WAV files after transcription. |
| `hotkeys` | See defaults above. | Global hotkey bindings. |

## Model Recommendations

Use `small` on `cpu` with `int8` for the default MVP experience.
Use `medium` if you want better accuracy and can accept slower transcription.
Use `large-v3` if you want the highest accuracy and have enough memory and patience.
Use `cuda` with `float16` or `int8_float16` when you have a supported NVIDIA GPU.

## Privacy

Transcription runs locally by default.
Temporary WAV files are written under `%TEMP%\WinWhisperDictate\`.
Temporary WAV files are deleted after transcription when `delete_audio_after_transcription` is `true`.
LLM cleanup is off by default.
LLM cleanup only runs when `cleanup_mode` is `llm` and `OPENAI_API_KEY` is set.

## Diagnostics

Run diagnostics from the activated virtual environment.

```powershell
python -m winwhisper.diagnostics
```

The diagnostics report includes Python, OS, microphone, model, dependency, API key presence, and temp directory checks.

## Known limitations

Non-text clipboard content is not preserved when pasting in the MVP.

## Troubleshooting

Some antivirus products that intercept TLS, such as Norton, break the first-run model download in two ways.
They set `SSLKEYLOGFILE` to a special device path, which crashes OpenSSL with a "no OPENSSL_Applink" error.
They also re-sign HTTPS traffic with a certificate that Python's default trust store rejects, causing `CERTIFICATE_VERIFY_FAILED`.
The app works around both automatically at startup: it removes an invalid `SSLKEYLOGFILE` value and trusts the Windows certificate store via `truststore`.
If you download models from your own scripts instead, apply the same two workarounds there.

## Packaging with PyInstaller

Install PyInstaller.

```powershell
pip install pyinstaller
```

Build a one-file executable with PyInstaller.

```powershell
pyinstaller --noconsole --onefile --name WinWhisperDictate src\winwhisper\main.py
```

If the one-file build has issues with faster-whisper, use the one-folder variant.

```powershell
pyinstaller --noconsole --name WinWhisperDictate src\winwhisper\main.py
```
