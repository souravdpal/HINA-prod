import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
core_dir = os.path.join(parent_dir, "core")
if core_dir not in sys.path:
    sys.path.insert(0, core_dir)


from core import hina_sdk
from mcp.server.fastmcp import FastMCP
from mcp_helper import web_google
from mcp_helper import gemini_helper
from mcp_helper import duck_duck
from core import hina_direct
from mcp_helper import yt_helper
from mcp_helper import vedio_helper
mcp = FastMCP("Web_search mcp")

@mcp.tool()
def play_youtube(que: str) -> str:
    hina_sdk.send_state(
            agent_name="Youtube connected",
            state="Searching...",
            msg="connected to server..",
            voice=False,
            icon="fa-brands fa-youtube",
            color="error",
            done=False

        )
    try:
        data = yt_helper.play_vedio(query=que)
        hina_sdk.send_state(
            agent_name="Youtube Player",
            state="sys_action",
            msg=f"playing Vedio..{data}",
            voice=False,
            icon="fa-brands fa-youtube",
            color="error",
            done=False  # NOT the final push — was `True` before, which
                        # closed the session early and caused every
                        # later push (including the real confirmation)
                        # to be dropped as "no active session".
        )
        hina_sdk.send_state(
            agent_name="Youtube Player",
            state="sys_confirmed",
            msg=f"playback confirmed {data[0]}",
            text=f"Play: {data[1]}",
            voice=False,
            icon="fa-brands fa-youtube",
            color="error",
            done=True 
        )
        return f"Started playing: {data[0]}"

    except RuntimeError as e:
        # RuntimeError from MiniPlayer.play() already carries the real
        # mpv failure reason (missing binary, crash on startup, dead
        # stream URL, etc.) — surface it verbatim instead of masking it.
        hina_sdk.send_state(
            agent_name="Logs",
            state="sys_logs",
            msg="playback failed",
            icon="fa-brands fa-youtube",
            color="error",
            text=str(e),
            done=True
        )
        return f"Failed to start playback: {str(e)}"

    except Exception as e:
        hina_sdk.send_state(
            agent_name="Logs",
            state="sys_logs",
            msg="Error in system",
            text=f"Error starting mpv: {str(e)}",
            icon="fa-brands fa-youtube",
            color="error",
            done=True
        )
        return f"Failed to start playback: {str(e)}"


if __name__ == "__main__":
    mcp.run()
