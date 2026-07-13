# Configuration

Speech keeps common controls in the tray or menu-bar UI. Advanced options live in a JSON settings file created on first run.

## Settings file

| Platform | Location |
| --- | --- |
| Windows | `%APPDATA%\Speech\settings.json` |
| macOS | `~/Library/Application Support/Speech/settings.json` |
| Linux | `$XDG_CONFIG_HOME/speech/settings.json`, usually `~/.config/speech/settings.json` |

Language selection, favorites, cleanup mode, microphone, and hotkeys can be changed from the app. Restart Speech after changing model, device, compute type, or custom vocabulary in JSON.

## Languages and favorites

Automatic detection is the default. Open **Language > Language Settings...** to search all 100 supported languages, select a fixed language, and pin up to three distinct favorites.

Favorites cannot use automatic detection or repeat another favorite. Favorite 1 defaults to English, Favorite 2 to Spanish, and Favorite 3 starts unassigned.

Changing a favorite changes the language forced by its quick action. It does not change that action's saved hotkey.

You can also set `language_mode` to `auto` or a supported code such as `en`, `es`, `fr`, `ja`, `ar`, `zh`, or `yue`.

## Microphone

Choose **Microphone > System Default** to follow the operating-system selection, or choose a specific input device.

**Test Microphone** opens the recording orb for five seconds and shows the live input level. The test does not write audio to disk or transcribe it.

If a selected device is disconnected, Speech keeps it visible as unavailable. Select System Default or another device, and confirm that the operating system has granted microphone access.

## Text cleanup

Cleanup runs after transcription and before paste. It never changes the recorded audio.

| Mode | Behavior | Network use |
| --- | --- | --- |
| `none` | Paste the faster-whisper result unchanged. | None |
| `basic` | Normalize whitespace and punctuation spacing, then capitalize the first alphabetic character. | None |
| `llm` | Improve punctuation, capitalization, disfluencies, and vocabulary spelling without translating or adding ideas. | Transcript text only |

`basic` is the default. LLM cleanup requires `OPENAI_API_KEY` in the environment before Speech starts and uses `gpt-4o-mini` by default.

If the API key is missing, the request fails, or it times out, Speech falls back to `basic` so dictation can still complete.

## Hotkeys

| Action | Windows | macOS | Linux |
| --- | --- | --- | --- |
| Start or stop | `Ctrl+Alt+Space` | `Control+Option+Space` | `Ctrl+Alt+Space` |
| Favorite 1 | `Ctrl+Shift+E` | `Control+Shift+E` | `Ctrl+Shift+E` |
| Favorite 2 | `Ctrl+Shift+S` | `Control+Shift+S` | `Ctrl+Shift+S` |
| Favorite 3 | Disabled | Disabled | Disabled |

Open **Hotkey Settings...**, select a suggestion or enter a combination, then save. Speech rejects duplicates and applies valid changes without a restart.

On Windows, an operating-system registration conflict keeps the previous working hotkeys. On macOS, Alt is displayed as Option and Win is displayed as Command.

Printable trigger keys require a modifier so normal typing cannot start dictation. Function keys such as `F8` can be used alone. Choose **Disabled** to leave an action without a shortcut.

### Serialized hotkeys

The settings file accepts serialized combinations:

```json
"hotkeys": {
  "toggle_recording": "<ctrl>+<shift>+<numpad_plus>"
}
```

A combination contains zero or more modifiers and exactly one trigger key. Supported modifiers are `<ctrl>`, `<alt>`, `<shift>`, and `<cmd>`.

macOS supports ASCII letters and digits, Space, Enter, Tab, Escape, Backspace, Delete, navigation keys, arrow keys, and `F1` through `F20`.

Windows also supports numpad keys, Plus, Minus, and function keys through `F24`. Linux uses the listener-based X11 backend and the standard cross-platform keys.

macOS rejects Option with a letter or number because its result changes with the keyboard layout. Prefer Space, a function key, or a shortcut without Option.

Remove an action from `hotkeys` to disable it. The persisted keys `force_english` and `force_spanish` remain for compatibility; `force_language_3` is the optional third action.

## Custom vocabulary

Whisper can guess unfamiliar names and jargon phonetically. Add a short list of exact spellings to bias transcription and LLM cleanup:

```json
"custom_vocabulary": ["README", "Claude Code", "winwhisper", "Andres Lee"]
```

Use product names, people's names, company terminology, and technical terms. A few dozen specific entries work better than hundreds. Restart Speech after editing the list.

## Model and performance

- `small` with CPU and `int8` is the default balance.
- `medium` improves accuracy at the cost of speed and memory.
- `large-v3` offers the highest accuracy and needs the most resources.
- Supported NVIDIA GPUs can use CUDA with `float16` or `int8_float16`.

The selected model downloads from Hugging Face on first use. CUDA does not apply to normal macOS builds.

## Settings reference

| Key | Default | Description |
| --- | --- | --- |
| `model_size` | `small` | faster-whisper model size. |
| `device` | `cpu` | Inference device such as `cpu` or `cuda`. |
| `compute_type` | `int8` | faster-whisper compute type. |
| `audio_input_device` | `null` | System Default, or a non-negative device index selected from the Microphone menu. |
| `language_mode` | `auto` | Automatic detection or one supported Whisper language code. |
| `language_favorites` | `["en", "es", null]` | Three distinct non-auto language codes; `null` leaves a slot unassigned. |
| `cleanup_mode` | `basic` | `none`, `basic`, or `llm`. |
| `paste_mode` | `auto` | Use the platform default and switch supported Windows/Linux terminals to `Ctrl+Shift+V`. |
| `delete_audio_after_transcription` | `true` | Delete temporary WAV files after transcription. |
| `check_for_updates` | `true` | Check GitHub Releases daily on Windows. Ignored on macOS and Linux. |
| `last_update_check_at` | `null` | Internal timestamp used to throttle update checks. |
| `hotkeys` | See defaults above | Global hotkey bindings. |
| `custom_vocabulary` | `[]` | Exact spellings used to bias transcription and cleanup. |

`paste_mode` can also force `clipboard_ctrl_shift_v` on Windows or Linux. Older `clipboard_ctrl_v` values retain automatic terminal detection for compatibility.
