# stt_module.py
import requests
import json
import time
import os

RESULT_FILE = 'speech_result.json'

def listen():
    try:
        print("🔄 Triggering browser to listen...")
        r = requests.get("http://localhost:3000/listen", timeout=10)
        
        if r.status_code != 200:
            print("❌", r.json().get("error"))
            return None

        print("🎙️  Mic opened → Speak clearly now!")

        # Wait for result file (max 15 seconds)
        start_time = time.time()
        while time.time() - start_time < 15:
            if os.path.exists(RESULT_FILE):
                try:
                    with open(RESULT_FILE, 'r') as f:
                        data = json.load(f)
                    text = data.get('text', '').strip()
                    if text:
                        print("✅ Received from browser!")
                        os.remove(RESULT_FILE)   # clean up
                        return text
                except:
                    pass
            time.sleep(0.2)

        print("⏰ Timeout - No speech result")
        return None

    except Exception as e:
        print("❌ Error:", str(e))
        return None


if __name__ == "__main__":
    print("=== HINA Voice Input (File-based) ===\n")
    print("Chrome must stay open at http://localhost:3000\n")

    while True:
        input("🔊 Press Enter to speak → ")
        text = listen()
        if text:
            print(f"\n✅ You said: {text}\n")
        else:
            print("\n⚠️  No text received.\n")