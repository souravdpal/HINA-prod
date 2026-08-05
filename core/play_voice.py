from hin_voice_engine import run_hina_voice
import sys


def main():
    if len(sys.argv) < 2:
        print("[PLAY_VOICE] No text received. Usage: play_voice.py <text>")
        sys.exit(1)

    text = sys.argv[1]

    # Print exactly what was received from the server
    print(f"[PLAY_VOICE] Received text: {text}")

    # TODO: hook up actual TTS / audio playback here.
    # e.g. call your TTS engine with `text` and play the resulting audio.
    speak(text)


def speak(text):
    print(text)
    #run_hina_voice(text=text)


if __name__ == "__main__":
    main()