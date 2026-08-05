import os
import sys
import json
import uuid
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core import model_call
from mcp.server.fastmcp import FastMCP
from core import hina_sdk

mcp = FastMCP("code server")

# All generated files land flat in this single directory, no matter what
# path the model puts in "### FILE: ...". /templates/index.html -> index.html
OUTPUT_DIR = Path(PROJECT_ROOT) / "Hina_db"


# --------------------------------------------------------------------------- #
# Plain functions (no MCP decoration) — these do the real work and can be
# called / tested / reused outside of the MCP tool itself.
# --------------------------------------------------------------------------- #

def flatten_filename(raw_path: str) -> str:
    """Take whatever path-looking string the model produced
    (e.g. 'templates/index.html', './static/css/style.css', 'app.py')
    and reduce it to just the filename — no directories, ever."""
    raw_path = raw_path.strip().replace("\\", "/")
    return raw_path.rsplit("/", 1)[-1].strip()


def make_storage_name(display_name: str) -> str:
    """Build the actual on-disk filename: a random UUID4 hex, keeping
    the original extension so file-type detection (icons, syntax
    highlighting, etc.) still works. Two files both called 'index.html'
    from two different runs will never collide, because neither run
    ever writes to a path derived from the model's own filename."""
    ext = Path(display_name).suffix  # includes the leading '.', or '' if none
    return f"{uuid.uuid4().hex}{ext}"


def save_code_files(files: dict[str, str], output_dir: Path = OUTPUT_DIR) -> list[dict]:
    """Takes a {relative_path: content} mapping (as returned by
    model_call.parse_code_files / AIResult.code_files) and writes every
    file FLAT into output_dir under a random UUID-based name, ignoring
    any folder structure the model tried to create. Returns a list of
    {"filename": <uuid-based name on disk>, "display_name": <original
    name the model gave it>} — 'filename' is what actually exists in
    Hina_db/ and what hina_sdk.send_file() must be called with;
    'display_name' is only for showing the user something readable."""
    output_dir.mkdir(parents=True, exist_ok=True)

    saved: list[dict] = []
    for raw_path, content in files.items():
        display_name = flatten_filename(raw_path)
        if not display_name:
            continue

        storage_name = make_storage_name(display_name)

        cleaned_content = content.replace("\xa0", " ").rstrip() + "\n"

        full_path = output_dir / storage_name
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(cleaned_content)

        saved.append({"filename": storage_name, "display_name": display_name})

    return saved


def generate_and_save_code(que: str, output_dir: Path = OUTPUT_DIR) -> list[dict]:
    """Calls the model in CODE_FILES mode, parses out every '### FILE:'
    block, and saves them flat into output_dir under random names.
    Returns a list of {"filename", "display_name"} dicts (empty list
    if the model produced nothing usable)."""
    ai = model_call.AICaller()

    result = ai.call(
        query=que,
        mode=model_call.Mode.CODE_FILES,
        format=model_call.Format.TEXT,
        prompt="You are an advanced coder. Only give code, nothing else, no chat tokens.",
    )

    if not result.ok or not result.code_files:
        return []

    return save_code_files(result.code_files, output_dir=output_dir)


def push_files_to_hina(saved_files: list[dict], agent_name: str = "CORE") -> None:
    """Iterate over every saved file and push a SYS_TOOL card for it.

    hina_sdk.py has no send_file() helper (only send_state / send_ui_json),
    so instead of calling a function that doesn't exist, we build the file
    card payload ourselves and send it through send_ui_json(). We include
    the view/download URLs that routes/hinaFiles.js already serves
    (GET /download/hina/files/:filename and .../:filename/save), so the
    frontend has everything it needs to render the card without any
    change to hina_sdk.py or the router.

    The last file is sent with done=True so the websocket closes only
    after every card has gone out.
    """
    file_count = len(saved_files)

    for i, item in enumerate(saved_files):
        is_last = i == file_count - 1
        file_payload = {
            "filename": item["filename"],
            "display_name": item["display_name"],
            "view_url": f"/download/hina/files/{item['filename']}",
            "download_url": f"/download/hina/files/{item['filename']}/save",
        }
        hina_sdk.send_ui_json(
            file_payload,
            ui_type="file",
            agent_name=agent_name,
            state="SYS_TOOL",
            msg=f"Generated {item['display_name']} ({i + 1}/{file_count})",
            color="tool",
            done=is_last,
        )


# --------------------------------------------------------------------------- #
# MCP tool — thin wrapper. Takes a user query, runs the pipeline above,
# pushes each file to the frontend as a card, and returns ONLY
# {"file_count": int, "files": [{"filename", "display_name"}, ...]} as JSON.
# --------------------------------------------------------------------------- #

@mcp.tool()
def make_code_files(query: str) -> str:
    """Generate code from a natural-language query, save every file
    produced flat into Hina_db under a random collision-proof name
    (no subfolders, even if the model tries to nest them), and push
    each one to the frontend as a file card. Returns JSON:
    {"file_count": N, "files": [{"filename": <uuid-name>,
    "display_name": <original name>}, ...]}."""
    saved_files = generate_and_save_code(query)

    if saved_files:
        push_files_to_hina(saved_files)

    return json.dumps({"file_count": len(saved_files), "files": saved_files})


if __name__ == "__main__":
    mcp.run()