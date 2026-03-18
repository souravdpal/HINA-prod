import subprocess
from pathlib import Path
import tempfile

def listen(timeout=30):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
        output_file = f.name

    proc = subprocess.Popen(
        ["node", "stt_chrome.js", output_file],
        cwd="/run/media/sourav/souravMain/HINA-prod",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        return ""

    text = Path(output_file).read_text(encoding='utf-8')
    Path(output_file).unlink()
    return text

if __name__ == "__main__":
    print("Listening... speak now.")
    result = listen()
    print("STT Result:", result)