import os
import shutil
import subprocess as sub
import uuid
from pathlib import Path


def _tool_available(name: str) -> bool:
    return shutil.which(name) is not None


def take_screenshot():
    save_dir = Path("/run/media/sourav/c66a6751-43e9-4dc0-8534-ef0403e815ed/hina_ai/scr")
    try:
        save_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"Could not create/access save directory {save_dir}: {e}")
        print("Is the drive mounted? Check with: lsblk / mount")
        return None

    file_path = save_dir / f"{uuid.uuid4().hex}.png"
    session_type = os.environ.get("XDG_SESSION_TYPE", "x11").lower()

    if session_type == "wayland":
        tool, cmd = "grim", ["grim", str(file_path)]
    else:
        tool, cmd = "scrot", ["scrot", str(file_path)]

    if not _tool_available(tool):
        print(f"'{tool}' is not installed. Install it with:")
        print(f"  sudo pacman -S {tool}")
        return None

    try:
        sub.run(cmd, check=True, capture_output=True, text=True, timeout=15)
    except sub.CalledProcessError as e:
        print(f"Screenshot command failed (exit {e.returncode}): {e.stderr.strip() if e.stderr else e}")
        return None
    except sub.TimeoutExpired:
        print(f"Screenshot command '{tool}' timed out after 15s.")
        return None
    except FileNotFoundError as e:
        print(f"Required screenshot tool not found: {e}")
        return None

    if not file_path.exists() or file_path.stat().st_size == 0:
        print(f"Screenshot command ran but no valid file was produced at {file_path}.")
        return None

    print(f"Screenshot saved at: {file_path}")
    return file_path


if __name__ == "__main__":
    take_screenshot()