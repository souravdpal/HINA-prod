# voice_engine.py
from piper import PiperVoice, SynthesisConfig
import wave
from pathlib import Path
import subprocess as sub
import os

def speak_text(text: str, output_file: str = "output.wav", 
               voice_file: str = "en_US-amy-medium.onnx",#"hi_IN-priyamvada-medium.onnx",
               volume: float = 0.6, length_scale: float = 1.0,
               noise_scale: float = 0.4, noise_w_scale: float = 0.4,
               normalize_audio: bool = True,
               auto_play: bool = True,
               cleanup: bool = True):
    """
    Convert text to speech using Piper and save as a WAV file, then optionally play and remove it.

    Tweaks:
    - length_scale = 1.0 → natural normal speed
    - noise_scale = 0.4 → less jitter, smoother
    - noise_w_scale = 0.4 → stable speaking variation
    - volume slightly higher for clarity
    """

    # Check if voice file exists
    if not Path(voice_file).is_file():
        raise FileNotFoundError(f"Voice file not found: {voice_file}")

    voice = PiperVoice.load(voice_file)

    syn_config = SynthesisConfig(
        volume=volume,
        length_scale=length_scale,
        noise_scale=noise_scale,
        noise_w_scale=noise_w_scale,
        normalize_audio=normalize_audio
    )

    # Generate WAV
    with wave.open(output_file, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        voice.synthesize_wav(text, wav_file, syn_config=syn_config)

    if auto_play:
        sub.run(["mpv", output_file])

    if cleanup:
        os.remove(output_file)

