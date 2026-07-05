import requests
import time
import os
import json

# Override with an env var if the server isn't on localhost, e.g. when this
# script runs on a different machine than the Node server.
SERVER_URL = os.environ.get("HINA_SERVER_URL", "http://localhost:3000")
RESULT_FILE = os.environ.get("HINA_RESULT_FILE", "speech_result.json")

REGISTER_RETRIES = 10
REGISTER_RETRY_DELAY = 1.0
LISTEN_TIMEOUT_S = 30


def _ping_listen():
    """Ask the server to unlock the browser UI. Returns True/False/None:
    True = browser registered and unlocked, False = server reachable but no
    browser registered yet, None = server unreachable."""
    try:
        r = requests.get(f"{SERVER_URL}/listen", timeout=3)
        if r.status_code == 200:
            return True
        return False
    except requests.exceptions.ConnectionError:
        return None
    except requests.exceptions.Timeout:
        return None


def listen():
    for attempt in range(1, REGISTER_RETRIES + 1):
        result = _ping_listen()
        if result is True:
            print("✅ Browser UI unlocked.")
            break
        elif result is False:
            print(f"🔄 Server up, no browser registered yet... ({attempt}/{REGISTER_RETRIES})")
        else:
            print(f"🔄 Server unreachable at {SERVER_URL} — is stt_ws.js running? ({attempt}/{REGISTER_RETRIES})")
        time.sleep(REGISTER_RETRY_DELAY)
    else:
        print("❌ Error: Browser never registered (or server never came up). Aborting.")
        return None

    if os.path.exists(RESULT_FILE):
        try:
            os.remove(RESULT_FILE)
        except OSError:
            pass

    start = time.time()
    while time.time() - start < LISTEN_TIMEOUT_S:
        if os.path.exists(RESULT_FILE):
            try:
                with open(RESULT_FILE, "r") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                # File may still be mid-write; give it one more beat.
                time.sleep(0.2)
                continue
            try:
                os.remove(RESULT_FILE)
            except OSError:
                pass
            return data.get("text")
        time.sleep(0.5)

    print("⌛ Timed out waiting for a response from the browser.")
    return None


if __name__ == "__main__":
    print(f"Using server: {SERVER_URL}")
    try:
        while True:
            input("Press Enter to trigger -> ")
            text = listen()
            if text:
                print(f"Received: {text}")
    except KeyboardInterrupt:
        print("\n👋 Exiting.")