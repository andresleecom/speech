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
The menu shows one entry per physical microphone and updates within a couple of seconds when a microphone is connected or disconnected, and always when the menu is rebuilt.

Speech identifies a saved microphone by `audio_input_device_name` plus `audio_input_device_host_api`, and keeps `audio_input_device` only as an index hint.

Every recording or wake-word open re-resolves that identity against the live device table.

If the saved device is missing, Speech falls back to System Default for that open, shows one toast for the change, and never writes the fallback into settings.

**Test Microphone** opens the recording orb for five seconds and shows the live input level.
The test does not write audio to disk or transcribe it.

If a selected device is disconnected, Speech keeps it visible as unavailable.
Select System Default or another device, and confirm that the operating system has granted microphone access.

## Text cleanup

Cleanup runs after transcription and before paste.
It never changes the recorded audio.

| Mode | Behavior | Network use |
| --- | --- | --- |
| `none` | Paste the faster-whisper result unchanged. | None |
| `basic` | Normalize whitespace and punctuation spacing, then capitalize the first alphabetic character when it starts the text or follows only opening punctuation. | None |
| `llm` | Improve punctuation, capitalization, disfluencies, and vocabulary spelling without translating or adding ideas. | Transcript text only |

`basic` is the default.
LLM cleanup requires `OPENAI_API_KEY` in the environment before Speech starts and uses `gpt-4o-mini` by default.

If the API key is missing, the request fails, or it times out, Speech falls back to `basic` so dictation can still complete.

`append_trailing_space` (default `true`) adds one trailing space when cleaned text ends in `.`, `!`, `?`, or `…`, so consecutive pastes do not glue together.
It is skipped when `cleanup_mode` is `none`, and it is applied only after stop-phrase trimming and empty checks.

`newline_commands` (default `false`) replaces the standalone spoken phrases `new line`, `new paragraph`, `nueva línea`, and `punto y aparte` with `\n` or `\n\n` during `basic` and `llm` cleanup.

After cleanup, Speech discards whole-text stock Whisper hallucinations such as "Thank you for watching", "Thanks for watching", "Gracias por ver", and Amara.org subtitle credits.
Those pastes are treated like an empty transcription.

## Hotkeys

Tap the dictation hotkey to toggle recording on or off.
Hold the dictation hotkey for at least 500 ms and release it to stop and transcribe.
Push-to-talk is available for Windows keyboard bindings only, while mouse bindings, macOS, and Linux remain toggle-only.

| Action | Windows | macOS | Linux |
| --- | --- | --- | --- |
| Start or stop | `Ctrl+Alt+Space` | `Control+Shift+Space` | `Ctrl+Alt+Space` |
| Favorite 1 | Disabled | Disabled | Disabled |
| Favorite 2 | Disabled | Disabled | Disabled |
| Favorite 3 | Disabled | Disabled | Disabled |

New profiles ship without quick-language shortcuts, because `Ctrl+Shift+E` and `Ctrl+Shift+S` are already taken by editors, browsers, and word processors.
Existing profiles keep every shortcut they have saved; changing a default never rewrites a settings file.

Open **Hotkey Settings...**, select a suggestion, or press **Record** and then the keys or a mouse button, then save.
Speech rejects duplicates.
On Windows and Linux, Record captures the chord from the keyboard; keys that a name table cannot express still bind through the active layout.
A Ctrl+Alt combination that AltGr would use to type a character is rejected so it cannot steal that key.

On Windows and Linux, valid changes rebind immediately without a restart. On macOS, Speech saves the new profile and does not restart the global-hotkey listener from the settings window: a packaged Speech.app relaunches after the settings dialog closes so the new shortcuts take effect; source/dev runs keep the saved settings and ask you to quit and reopen Speech. If the save fails, the previous hotkeys stay in effect.

On Windows, an operating-system registration conflict keeps the previous working hotkeys. On macOS, Alt is displayed as Option and Win is displayed as Command.

Printable trigger keys require a modifier so normal typing cannot start dictation. Function keys such as `F8` can be used alone. Choose **Disabled** to leave an action without a shortcut.

### Mouse buttons

Any action can be bound to a mouse button instead of a key.
In **Hotkey Settings...**, press **Record** next to an action and then press the mouse button you want. Whatever the button reports is what gets bound, so mice with extra buttons work without Speech knowing the model.

Side buttons, the middle button, and the right button can be bound on their own.
Left click always needs a modifier, because bound bare it would swallow the click you need to undo it.
Mouse buttons can be combined with modifiers, for example `Ctrl + Mouse Back`.

On Windows, a bound button no longer performs its normal action: binding **Mouse Back** starts dictation and does not navigate back. Every other button and every unbound modifier combination passes through untouched.
On macOS and Linux the click still performs its normal action as well, because the only suppression available there is all-or-nothing for the whole mouse.

Serialized names follow the button names the operating system reports:

```json
"hotkeys": {
  "toggle_recording": "<mouse_x1>",
  "force_english": "<ctrl>+<mouse_middle>"
}
```

`<mouse_x1>` is the back button and `<mouse_x2>` is forward. `mouse_back` and `mouse_forward` are accepted as aliases.

If a button does nothing when you press Record, the mouse vendor's software is probably remapping it to a keystroke before Windows sees it as a mouse button. Logitech Options+ and similar tools do this by default on gesture buttons. Either set that button to "Mouse button" in the vendor software, or bind the keystroke it sends as a normal keyboard shortcut. `python scripts/probe_mouse_buttons.py` lists exactly which buttons reach the operating system.

### Serialized hotkeys

The settings file accepts serialized combinations:

```json
"hotkeys": {
  "toggle_recording": "<ctrl>+<shift>+<numpad_plus>"
}
```

A combination contains zero or more modifiers and exactly one trigger key. Supported modifiers are `<ctrl>`, `<alt>`, `<shift>`, and `<cmd>`.

macOS supports ASCII letters and digits, Space, Enter, Tab, Escape, Backspace, Delete, navigation keys, arrow keys, and `F1` through `F20`.

Windows also supports numpad keys, Plus, Minus, and function keys through `F24`.
Linux uses the listener-based X11 backend, so it accepts letters, digits, `F1` through `F20`, Space, Enter, Tab, Escape, Backspace, Delete, Insert, Home, End, Page Up, Page Down, the arrow keys, and numpad keys.
Any other trigger is rejected on Linux rather than saved as a shortcut that could never fire.

macOS rejects Option with a letter or number because its result changes with the keyboard layout. Prefer Space, a function key, or a shortcut without Option.

Remove an action from `hotkeys` to disable it. The persisted keys `force_english` and `force_spanish` remain for compatibility; `force_language_3` is the optional third action.

## Custom vocabulary

Whisper can guess unfamiliar names and jargon phonetically. Add a short list of exact spellings to bias transcription and LLM cleanup:

```json
"custom_vocabulary": ["README", "Claude Code", "winwhisper", "Andres Lee"]
```

Use product names, people's names, company terminology, and technical terms. A few dozen specific entries work better than hundreds. Restart Speech after editing the list.

## Model and performance

- `small` (~464 MB) with CPU and `int8` is the default balance.
- `medium` (~1530 MB) improves accuracy at the cost of speed and memory.
- `large-v3` (~3090 MB) offers the highest accuracy and needs the most resources.
- `large-v3-turbo` (~1620 MB) is a faster large model with a smaller download.
- Supported NVIDIA GPUs can use CUDA with `float16` or `int8_float16`, once the CUDA math libraries are installed separately.

The selected model downloads from Hugging Face on first use. CUDA does not apply to normal macOS builds.

### Running on an NVIDIA GPU

**The packaged Speech builds do not include the CUDA math libraries, so `cuda` works only if you supply them yourself.**
The installers ship CTranslate2 with CUDA support compiled in, but not `cublas64_12.dll`, which the encoder loads the first time it actually transcribes.
Without it, the model loads on the GPU and then fails on the first real dictation. Speech detects that and continues on the CPU.

To use the GPU, install the NVIDIA CUDA 12 runtime, or `pip install nvidia-cublas-cu12`, so that `cublas64_12.dll` is on the library search path.
Then set the device and restart Speech.

```json
"device": "cuda",
"compute_type": "float16"
```

`gpu` is accepted as a spelling of `cuda`, and `auto` picks the GPU when one is usable and the CPU otherwise.
Any other value, such as `mps` or `rocm`, is rejected on load and Speech keeps using the CPU.

Speech falls back to CPU `int8` and notifies you rather than failing a dictation, whether the GPU fails when the model loads or later when it first runs.
Run `speech --diagnostics` to see the configured device next to the number of CUDA devices actually detected.
A non-zero count only means a GPU was found; it does not prove the math libraries are present.

## Updates

On Windows, Speech checks GitHub Releases once a day and can install an update from **Check for Updates** in the tray menu.

Choosing to install downloads the installer, verifies its SHA-256, and waits for Speech to exit before running it, so the installer is never fighting a locked binary.
Speech reopens on its own once the install finishes.

Installing a new version removes the previous one first, so each update is a clean install rather than a new build layered over the old files.
Your settings, hotkeys, custom vocabulary, and logs live in `%APPDATA%\Speech` and are never touched by this.

Installers are cached in `%APPDATA%\Speech\updates`. Each update deletes the installers left by earlier ones before downloading the new one, so the directory holds at most the current download rather than growing by roughly 73 MB per release.

macOS and Linux updates are installed manually from the Releases page.

## Settings reference

| Key | Default | Description |
| --- | --- | --- |
| `model_size` | `small` | faster-whisper model size. |
| `device` | `cpu` | `cpu`, `cuda` for an NVIDIA GPU (`gpu` also works), or `auto`. |
| `compute_type` | `int8` | faster-whisper compute type, such as `int8`, `float16`, or `int8_float16`. |
| `audio_input_device` | `null` | Index hint for the selected microphone, or `null` for System Default. |
| `audio_input_device_name` | `null` | Stable device name used with the host API to re-resolve the microphone. |
| `audio_input_device_host_api` | `null` | Host API name on Windows/Linux, or the AVFoundation unique ID on macOS. |
| `language_mode` | `auto` | Automatic detection or one supported Whisper language code. |
| `language_favorites` | `["en", "es", null]` | Three distinct non-auto language codes; `null` leaves a slot unassigned. |
| `cleanup_mode` | `basic` | `none`, `basic`, or `llm`. |
| `append_trailing_space` | `true` | After `basic` or `llm` cleanup, append one space when the text ends in `.`, `!`, `?`, or `…`. |
| `newline_commands` | `false` | When true, replace spoken `new line` / `new paragraph` / `nueva línea` / `punto y aparte` with real newlines during cleanup. |
| `paste_mode` | `auto` | Use the platform default and switch supported Windows/Linux terminals to `Ctrl+Shift+V`. |
| `delete_audio_after_transcription` | `true` | Delete temporary WAV files after transcription. |
| `check_for_updates` | `true` | Check GitHub Releases daily on Windows. Ignored on macOS and Linux. See [Updates](#updates). |
| `last_update_check_at` | `null` | Internal timestamp used to throttle update checks. |
| `hotkeys` | See defaults above | Global hotkey bindings. |
| `custom_vocabulary` | `[]` | Exact spellings used to bias transcription and cleanup. |
| `wake_word_enabled` | `false` | Hands-free dictation: say a wake phrase to start, the stop phrase or a silence to finish. |
| `wake_phrases` | `["hey speech", "oye speech"]` | Phrases that start recording while the wake word is enabled; any one of them triggers it. |
| `wake_phrase_languages` | `{"hey speech": "en", "oye speech": "es"}` | Language override for the take started by each wake phrase. Absent phrases keep `language_mode`. Keys are normalised; values are Whisper language codes. |
| `stop_phrase` | `"stop"` | Spoken phrase that ends a wake-word recording when it is the last thing said before a pause; it is trimmed from the pasted text. |
| `wake_silence_timeout_seconds` | `3.0` | Seconds of silence after the last detected speech that also end a wake-word recording (1-30). |
| `wake_model_size` | `"tiny"` | faster-whisper model for wake/stop detection. `tiny` is safe on CPU; on a GPU, `base` or `small` hear accented or code-switched phrases (e.g. "oye speech") much better. Uses the same `device`/`compute_type` as transcription. |

The wake word runs a small local Whisper model over a rolling audio window, using the same `device`/`compute_type` as transcription (CUDA included, with CPU fallback); it works alongside the hotkeys, which stay active either way.
Toggle it from the tray menu or by setting `wake_word_enabled`.

Windows are gated by an RMS level check and then Silero VAD before the model runs.
Detection uses one prompted pass with the configured phrases as `initial_prompt`, so short cues in any language (e.g. `"oye speech"`) land without a language-hint retry loop.
The stop phrase must be the trailing words of the transcript, spoken just before a short pause; mid-sentence uses such as "stop the car now" do not end the take.
Silence timeout is counted from the last VAD-detected speech in the recording tail.

`paste_mode` can also force `clipboard_ctrl_shift_v` on Windows or Linux. Older `clipboard_ctrl_v` values retain automatic terminal detection for compatibility.
