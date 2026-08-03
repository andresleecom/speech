"""Interactive wake-word probe: record a phrase and see what the detector hears.

Run it in your own terminal:

    .venv\\Scripts\\python scripts\\wake_word_probe.py

Each round prompts you, records a few seconds from the microphone, then shows
the auto/es/en transcripts from the wake-word model and whether the phrase
would have fired. Useful for tuning wake phrases and checking the microphone.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np

from winwhisper.config import load_settings
from winwhisper.wake_word import (
    RollingBuffer,
    WhisperPhraseDetector,
    audio_level,
    boost_audio,
    language_hints,
    phrase_in_text,
)
from winwhisper.wake_word_source import SounddeviceSource

RECORD_SECONDS = 4.0
RECORDINGS_DIR = Path(__file__).resolve().parent.parent / "probe_recordings"


def record(seconds: float, device: int | None) -> np.ndarray:
    buffer = RollingBuffer(seconds=seconds + 1.0)
    source = SounddeviceSource(audio_input_device=device)
    source.start(buffer.append)
    print("  Grabando", end="", flush=True)
    for _ in range(int(seconds)):
        time.sleep(1)
        print(".", end="", flush=True)
    source.stop()
    print(" listo.")
    return buffer.snapshot()


def save_round(audio: np.ndarray, round_number: int) -> Path:
    import wave

    RECORDINGS_DIR.mkdir(exist_ok=True)
    path = RECORDINGS_DIR / f"round_{round_number}.wav"
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(audio.tobytes())
    return path


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    settings = load_settings()
    # Candidate phrases can be passed on the command line to try new wake
    # words without touching the settings, e.g.:
    #   wake_word_probe.py escucha dicta computer
    phrases = sys.argv[1:] or settings.wake_phrases
    languages = language_hints(settings.language_mode, settings.language_favorites)
    print(f"Frases activas: {phrases}")
    print(f"Idiomas de respaldo: {languages or '(ninguno)'}")
    print(f"Dispositivo de audio: {settings.audio_input_device or 'predeterminado'}")
    print(f"Modelo: {settings.wake_model_size} en {settings.device}/{settings.compute_type}\n")

    detector = WhisperPhraseDetector(
        device=str(settings.device),
        compute_type=str(settings.compute_type),
        languages=languages,
        model_size=str(settings.wake_model_size),
    )

    round_number = 0
    while True:
        round_number += 1
        answer = input(
            f"[Ronda {round_number}] Presiona Enter y di una frase de activación "
            "(o escribe 'salir'): "
        )
        if answer.strip().lower() in {"salir", "exit", "q", "quit"}:
            break

        audio = record(RECORD_SECONDS, settings.audio_input_device)
        wav_path = save_round(audio, round_number)
        level = audio_level(boost_audio(audio))
        print(f"  Nivel (con ganancia): {level:.3f}  (guardado: {wav_path.name})")

        audio_float = boost_audio(audio).astype("float32") / 32768.0
        heard_any = False
        for language in [None, *languages]:
            transcript = detector._run_with_fallback(audio_float, language=language)
            matched = any(phrase_in_text(phrase, transcript) for phrase in phrases)
            heard_any = heard_any or matched
            marker = "  <-- COINCIDE, habría disparado" if matched else ""
            print(f"  [{language or 'auto':>5}] {transcript!r}{marker}")
        if not heard_any:
            print("  Ninguna pasada coincidió con las frases activas.")
        print()


if __name__ == "__main__":
    main()
