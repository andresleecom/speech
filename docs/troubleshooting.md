# Troubleshooting

Start with the latest release. Then run diagnostics or follow the platform-specific checks below.

## Diagnostics

From an activated development environment:

```bash
python -m winwhisper.diagnostics
```

The report covers Python, the operating system, configured and available microphones, model settings, dependencies, API-key presence, and the temporary directory.

Packaged applications also support `--diagnostics` from a terminal.

## macOS hotkey does not respond

1. Open **System Settings > Privacy & Security**.
2. Enable Speech under both **Accessibility** and **Input Monitoring**.
3. If Speech was replaced or updated, switch both permissions off and on again.
4. Quit Speech from its menu-bar icon, then reopen it from Applications.

Input Monitoring lets Speech receive global hotkeys. Accessibility lets it restore focus and paste into another application.

If Speech is missing from either list, launch it once, retry the permission request, and reopen the privacy panes.

## macOS or Windows blocks the app

Current releases are not code-signed. On macOS, right-click Speech and choose **Open**. On Windows, inspect the SmartScreen prompt before choosing to run the app.

Every release includes a `.sha256` file for each asset. Compare your download with the matching checksum on the release page.

```powershell
certutil -hashfile Speech-Setup-<version>.exe SHA256
```

```bash
shasum -a 256 Speech-<version>.dmg
shasum -a 256 Speech-<version>-intel.dmg
sha256sum Speech-<version>.AppImage
sha256sum Speech-<version>.deb
```

## Linux tray icon or hotkey is missing

Speech requires an X11 session for global hotkeys, focus restoration, and the floating orb. Wayland is not supported yet.

The desktop must provide an AppIndicator-compatible tray. Ubuntu includes one. Debian GNOME users can install `gnome-shell-extension-appindicator` if the icon is absent.

AppImage users may need FUSE support:

```bash
sudo apt install fuse3 libfuse2
chmod +x Speech.AppImage
./Speech.AppImage
```

If FUSE mounting is unavailable, use the supported extraction fallback:

```bash
APPIMAGE_EXTRACT_AND_RUN=1 ./Speech.AppImage
```

## LLM cleanup does not run

Set `OPENAI_API_KEY` before launching Speech and select **Cleanup > LLM**.

If the key is unavailable, OpenAI returns an error, or the request times out, Speech intentionally applies Basic cleanup so the transcription can still paste.

Only transcript text is sent for LLM cleanup. Recorded audio never leaves the computer.

## Windows model download fails

Some antivirus products intercept TLS during the first model download. They can set `SSLKEYLOGFILE` to an invalid device path or replace HTTPS certificates with a locally trusted certificate.

Speech removes invalid `SSLKEYLOGFILE` values and uses the Windows certificate store through `truststore` automatically.

If the failure continues, run diagnostics, confirm that GitHub and Hugging Face are reachable, and temporarily test without HTTPS inspection according to your security policy.

## Text did not paste

Speech leaves the transcription on the clipboard after every paste attempt. Return to the target app and press `Ctrl+V` on Windows/Linux or `Cmd+V` on macOS.

Windows and Linux use `Ctrl+Shift+V` automatically for supported terminal processes. Other applications receive `Ctrl+V`; macOS always receives `Cmd+V`.

## Microphone has no signal

Open **Microphone > Test Microphone** and watch the orb for input activity. If a saved device is unavailable, choose **System Default** or another connected input.

Confirm microphone permission in the operating-system settings. The five-second microphone test does not write audio to disk or start a transcription.

## Still stuck?

Search the [existing issues](https://github.com/andresleecom/speech/issues) or open a new one with your operating system, Speech version, diagnostics output, and reproducible steps.

Report security problems privately through [SECURITY.md](../SECURITY.md), not through a public issue.
