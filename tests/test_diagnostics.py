import winwhisper.diagnostics as diagnostics
from winwhisper.audio_inputs import AudioInputDevice


def test_microphone_diagnostics_marks_default_and_selected_device(monkeypatch, capsys):
    devices = (
        AudioInputDevice(index=1, name="Built-in Mic", input_channels=2),
        AudioInputDevice(index=3, name="USB Mic", input_channels=1),
    )
    monkeypatch.setattr(diagnostics, "list_audio_input_devices", lambda: devices)
    monkeypatch.setattr(diagnostics, "default_audio_input_device", lambda: 1)

    diagnostics._print_microphone_devices(3)

    output = capsys.readouterr().out
    assert "configured: USB Mic [3]" in output
    assert "Built-in Mic [1] (2 input channels; system default)" in output
    assert "USB Mic [3] (1 input channels; selected)" in output
