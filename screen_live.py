import os
import subprocess as sub
import uuid
from pathlib import Path

def take_screenshot():
    save_dir = Path("/run/media/sourav/souravMain/HINA-prod/scr")
    save_dir.mkdir(parents=True, exist_ok=True)
    file_path = save_dir / f"{uuid.uuid4().hex}.png"

    session_type = os.environ.get("XDG_SESSION_TYPE", "x11").lower()

    try:
        if session_type == "wayland":
            # grim works for Wayland
            sub.run(["grim", str(file_path)], check=True)
        else:
            # scrot works for X11
            sub.run(["scrot", str(file_path)], check=True)
        print(f"Screenshot saved at: {file_path}")
        return file_path
    except FileNotFoundError as e:
        print("Required screenshot tool not found:", e)
    except sub.CalledProcessError as e:
        print("Screenshot command failed:", e)


take_screenshot()
